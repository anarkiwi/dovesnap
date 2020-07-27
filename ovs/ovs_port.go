package ovs

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"

	log "github.com/Sirupsen/logrus"
)

func (ovsdber *ovsdber) lowestFreePortOnBridge(bridgeName string) (lowestFreePort uint, err error) {
	output, err := OfCtl("dump-ports-desc", bridgeName)
	if err != nil {
		return 0, err
	}
	var ofportNumberDump = regexp.MustCompile(`^\s*(\d+)\(\S+\).+$`)
	existingOfPorts := []int{}
	for _, line := range strings.Split(string(output), "\n") {
		match := ofportNumberDump.FindAllStringSubmatch(line, -1)
		if len(match) > 0 {
			ofport, _ := strconv.Atoi(match[0][1])
			existingOfPorts = append(existingOfPorts, ofport)
		}
	}
	sort.Ints(existingOfPorts)
	intLowestFreePort := 1
	for _, existingPort := range existingOfPorts {
		if existingPort != intLowestFreePort {
			break
		}
		intLowestFreePort++
	}
	return uint(intLowestFreePort), nil
}

func (ovsdber *ovsdber) addInternalPort(bridgeName string, portName string, tag uint) (uint, string, error) {
	lowestFreePort, err := ovsdber.lowestFreePortOnBridge(bridgeName)
	if err != nil {
		return lowestFreePort, "", err
	}
	if tag != 0 {
		value, err := VsCtl("add-port", bridgeName, portName, fmt.Sprintf("tag=%u", tag), "--", "set", "Interface", portName, fmt.Sprintf("ofport_request=%d", lowestFreePort))
		return lowestFreePort, value, err
	}
	value, err := VsCtl("add-port", bridgeName, portName, "--", "set", "Interface", portName, fmt.Sprintf("ofport_request=%d", lowestFreePort))
	return lowestFreePort, value, err
}

func (ovsdber *ovsdber) addPatchPort(bridgeName string, bridgeNamePeer string, portName string, portNamePeer string) (uint, uint, error) {
	lowestFreePort, err := ovsdber.lowestFreePortOnBridge(bridgeName)
	if err != nil {
		return 0, 0, err
	}
	lowestFreePortPeer, err := ovsdber.lowestFreePortOnBridge(bridgeNamePeer)
	if err != nil {
		return 0, 0, err
	}
	_, err = VsCtl("add-port", bridgeName, portName, "--", "set", "Interface", portName, fmt.Sprintf("ofport_request=%d", lowestFreePort))
	_, err = VsCtl("set", "interface", portName, "type=patch")
	_, err = VsCtl("add-port", bridgeNamePeer, portNamePeer, "--", "set", "Interface", portNamePeer, fmt.Sprintf("ofport_request=%d", lowestFreePortPeer))
	_, err = VsCtl("set", "interface", portNamePeer, "type=patch")
	_, err = VsCtl("set", "interface", portName, fmt.Sprintf("options:peer=%s", portNamePeer))
	_, err = VsCtl("set", "interface", portNamePeer, fmt.Sprintf("options:peer=%s", portName))
	return lowestFreePort, lowestFreePortPeer, err
}

func (ovsdber *ovsdber) deletePatchPort(bridgeName string, bridgeNamePeer string) error {
	// Only need to delete one side, as the other side is the bridge that got removed completely
	_, err := VsCtl("del-port", bridgeName, bridgeName+"-patch-"+bridgeNamePeer)
	return err
}

func (ovsdber *ovsdber) deletePort(bridgeName string, portName string) error {
	_, err := VsCtl("del-port", bridgeName, portName)
	return err
}

func (ovsdber *ovsdber) getOfPortNumber(portName string) (uint, error) {
	ofport, err := VsCtl("get", "Interface", portName, "ofport")
	if err != nil {
		log.Errorf("Unable to get interface %s ofport number because: %v", portName, err)
		return 0, err
	}
	ofportNum, err := strconv.ParseUint(ofport, 10, 32)
	if err != nil {
		log.Errorf("Unable to convert ofport number %v to an unsigned integer because: %v", ofport, err)
		return 0, err
	}
	return uint(ofportNum), nil
}

func (ovsdber *ovsdber) addVxlanPort(bridgeName string, portName string, peerAddress string) (string, error) {
	// http://docs.openvswitch.org/en/latest/faq/vxlan/
	value, err := VsCtl("add-port", bridgeName, portName, "--", "set", "interface", portName, "type=vxlan", fmt.Sprintf("options:remote_ip=%s", peerAddress))
	return value, err
}
