#!/bin/bash

export TMPDIR=$(mktemp -d)
export FAUCET_CONFIG=$TMPDIR/etc/faucet/faucet.yaml
export GAUGE_CONFIG=$TMPDIR/etc/faucet/gauge.yaml
if [ ! -d "$TMPDIR" ] ; then
	exit 1
fi
mkdir -p $TMPDIR/etc/faucet

echo configuring faucet: $FAUCET_CONFIG

sudo rm -f $FAUCET_CONFIG
cat >$FAUCET_CONFIG <<EOFC || exit 1
acls:
  allowall:
  - rule:
      actions:
        allow: 1
  denyall:
  - rule:
      actions:
        allow: 0
dps:
  testnet:
    dp_id: 0x1
    hardware: Open vSwitch
    interfaces:
        0xfffffffe:
            native_vlan: 100
            opstatus_reconf: false
    interface_ranges:
        1-10:
            native_vlan: 100
            acls_in: [denyall]
EOFC
cat >$GAUGE_CONFIG <<EOGC || exit 1
faucet_configs:
    - '/etc/faucet/faucet.yaml'
watchers:
    port_status_poller:
        type: 'port_state'
        all_dps: True
        db: 'prometheus'
    port_stats_poller:
        type: 'port_stats'
        all_dps: True
        interval: 30
        db: 'prometheus'
dbs:
    prometheus:
        type: 'prometheus'
        prometheus_addr: '0.0.0.0'
        prometheus_port: 9303
EOGC
echo creating keys
mkdir -p /opt/dovesnap/faucetconfrpc || exit 1
FAUCET_PREFIX=$TMPDIR docker-compose -f docker-compose.yml -f docker-compose-standalone.yml up faucet_certstrap || exit 1
ls -al /opt/dovesnap/faucetconfrpc/client.key || exit 1
echo starting dovesnap infrastructure
docker-compose build && FAUCET_PREFIX=$TMPDIR docker-compose -f docker-compose.yml -f docker-compose-standalone.yml up -d || exit 1
echo waiting for Faucet/Gauge
for port in 9302 9302 ; do
	wget --retry-connrefused --tries=20 -q -O/dev/null localhost:$port > /dev/null || exit 1
done
docker ps -a
echo creating testnet
docker network create testnet -d ovs -o ovs.bridge.mode=nat -o ovs.bridge.dpid=0x1 -o ovs.bridge.controller=tcp:127.0.0.1:6653,tcp:127.0.0.1:6654 || exit 1
docker network ls
echo waiting for OVS DP to come up
for port in 9302 9303 ; do
	DPSTATUS=""
	while [ "$DPSTATUS" == "" ] ; do
		sleep 1
		DPSTATUS=$(wget -q -O- localhost:$port|grep -E "^dp_status"|grep -E "1.0$")
	done
done
echo creating testcon
# github test runner can't use ping.
docker run -d --label="dovesnap.faucet.portacl=allowall" --net=testnet --rm --name=testcon busybox sleep 1d
RET=$?
if [ "$RET" != "0" ] ; then
	echo testcon container creation returned: $RET
	exit 1
fi
while [ "$(sudo grep -c allowall $FAUCET_CONFIG)" != "2" ] ; do
	echo waiting for ACL to be applied
	docker logs `docker ps |grep dovesnap_plugin|cut -f 1 -d " "`
	sudo cat $FAUCET_CONFIG
        sleep 1
done
sudo grep "description: /testcon" $FAUCET_CONFIG || exit 1
echo verifying networking
docker exec -t testcon wget -q -O- bing.com || exit 1
docker rm -f testcon || exit 1
docker network rm testnet || exit 1
FAUCET_PREFIX=$TMPDIR docker-compose -f docker-compose.yml -f docker-compose-standalone.yml stop
rm -rf $TMPDIR
