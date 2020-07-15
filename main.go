package main

import (
	"os"

	ovs "dovesnap/ovs"
	log "github.com/Sirupsen/logrus"
	"github.com/codegangsta/cli"
	"github.com/docker/go-plugins-helpers/network"
)

const (
	version = "0.1.1"
)

func main() {
	flagDebug := cli.BoolFlag{
		Name:  "debug, d",
		Usage: "enable debugging",
	}
	flagFaucetconfrpcServerName := cli.StringFlag{
		Name:  "faucetconfrpc_addr",
		Usage: "address of faucetconfrpc server",
		Value: "localhost",
	}
	flagFaucetconfrpcServerPort := cli.IntFlag{
		Name:  "faucetconfrpc_port",
		Usage: "port for faucetconfrpc server",
		Value: 59999,
	}
	flagFaucetconfrpcKeydir := cli.StringFlag{
		Name:  "faucetconfrpc_keydir",
		Usage: "directory with keys for faucetconfrpc server",
		Value: "/faucetconfrpc",
	}
	flagStackingInterfaces := cli.StringFlag{
		Name:  "stacking_ports",
		Usage: "comma separated list of [dpid:port:interface_name] to use for stacking",
	}
	app := cli.NewApp()
	app.Name = "dovesnap"
	app.Usage = "Docker Open vSwitch Network Plugin"
	app.Version = version
	app.Flags = []cli.Flag{
		flagDebug,
		flagFaucetconfrpcServerName,
		flagFaucetconfrpcServerPort,
		flagFaucetconfrpcKeydir,
		flagStackingInterfaces,
	}
	app.Action = Run
	app.Run(os.Args)
}

// Run initializes the driver
func Run(ctx *cli.Context) {
	if ctx.Bool("debug") {
		log.SetLevel(log.DebugLevel)
	}
	d, err := ovs.NewDriver(
		ctx.String("faucetconfrpc_addr"),
		ctx.Int("faucetconfrpc_port"),
		ctx.String("faucetconfrpc_keydir"),
		ctx.String("stacking_ports"))
	if err != nil {
		panic(err)
	}
	h := network.NewHandler(d)
	h.ServeUnix(ovs.DriverName, 0)
}
