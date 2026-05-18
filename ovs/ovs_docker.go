package ovs

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/moby/moby/api/types/container"
	"github.com/moby/moby/api/types/network"
	"github.com/moby/moby/client"
	log "github.com/sirupsen/logrus"
)

type dockerer struct {
	client *client.Client
}

func (c *dockerer) mustGetDockerClient() {
	docker, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		panic(fmt.Errorf("could not connect to docker: %s", err))
	}
	c.client = docker
}

func (c *dockerer) mustGetShortEngineID() string {
	result, err := c.client.Info(context.Background(), client.InfoOptions{})
	if err != nil {
		panic(err)
	}
	log.Debugf("Docker Engine ID %s:", result.Info.ID)
	engineId := base36to16(strings.Split(result.Info.ID, ":")[0])
	return engineId
}

func (c *dockerer) mustGetNetworkInspectFromID(NetworkID string) network.Inspect {
	for i := 0; i < dockerRetries; i++ {
		netInspect, err := c.client.NetworkInspect(context.Background(), NetworkID, client.NetworkInspectOptions{})
		if err == nil {
			return netInspect.Network
		}
		time.Sleep(1 * time.Second)
	}
	panic(fmt.Errorf("network %s not found", NetworkID))
}

func (c *dockerer) mustGetNetworkNameFromID(NetworkID string) string {
	return c.mustGetNetworkInspectFromID(NetworkID).Name
}

func (c *dockerer) mustGetNetworkList() map[string]string {
	networkList, err := c.client.NetworkList(context.Background(), client.NetworkListOptions{})
	if err != nil {
		panic(fmt.Errorf("could not get docker networks: %s", err))
	}
	netlist := make(map[string]string)
	for _, net := range networkList.Items {
		if net.Driver == DriverName {
			netlist[net.ID] = net.Name
		}
	}
	return netlist
}

func (c *dockerer) getContainerFromEndpoint(NetworkID string, EndpointID string) (container.InspectResponse, error) {
	for i := 0; i < dockerRetries; i++ {
		log.Debugf("about to inspect network %+v", NetworkID)
		netInspect := c.mustGetNetworkInspectFromID(NetworkID)
		for containerID, containerInfo := range netInspect.Containers {
			if containerInfo.EndpointID == EndpointID {
				log.Debugf("about to inspect container %+v", EndpointID)
				ctx, cancel := context.WithTimeout(context.Background(), dockerRetries*time.Second)
				defer cancel()
				containerInspect, err := c.client.ContainerInspect(ctx, containerID, client.ContainerInspectOptions{})
				if err != nil {
					continue
				}
				log.Debugf("returned %+v", containerInspect)
				return containerInspect.Container, nil
			}
		}
		time.Sleep(2 * time.Second)
	}
	return container.InspectResponse{}, fmt.Errorf("endpoint %s not found", EndpointID)
}
