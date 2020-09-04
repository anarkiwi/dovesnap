#!/usr/bin/python3

import argparse
import re
import os
import subprocess
import docker
from faucetconfrpc.faucetconfrpc_client_lib import FaucetConfRpcClient
from graphviz import Digraph


class GraphDovesnapException(Exception):
    pass


class GraphDovesnap:

    DOVESNAP_NAME = 'dovesnap_plugin'
    OVS_NAME = 'dovesnap_ovs'
    DRIVER_NAME = 'ovs'
    OFP_LOCAL = 4294967294
    DOCKER_URL = 'unix://var/run/docker.sock'
    OUTPUT_FILE = 'dovesnapviz'
    PATCH_PREFIX = 'ovp'
    VM_PREFIX = 'vnet'
    DOVESNAP_MIRROR = '99'

    def __init__(self, args):
        self.args = args

    def _get_named_container(self, client, name, strict=True):
        for container in client.containers(filters={'name': name}):
            if not strict:
                return container
            for container_name in container['Names']:
                if name in container_name:
                    return container
        return None

    def _get_named_container_hi(self, client_hi, name, strict=True):
        for container in client_hi.containers.list(filters={'name': name}):
            if not strict:
                return container
            if container.name == name:
                return container
        return None

    def _scrape_container_cmd(self, name, cmd, strict=True):
        client_hi = docker.DockerClient(base_url=self.DOCKER_URL)
        container = self._get_named_container_hi(client_hi, name, strict=strict)
        (dump_exit, output) = container.exec_run(cmd)
        if dump_exit != 0:
            raise GraphDovesnapException('%s: %s', cmd, output)
        return output.splitlines()

    def _scrape_ovs(self, cmd):
        return self._scrape_container_cmd(self.OVS_NAME, cmd, strict=False)

    def _get_dovesnap_networks(self, client):
        return client.networks(filters={'driver': self.DRIVER_NAME})

    def _dovesnap_bridgename(self, net_id):
        return 'ovsbr-%s' % net_id[:5]

    def _get_vm_options(self, network, ofport):
        vm_options = []
        client = FaucetConfRpcClient(self.args.key, self.args.cert, self.args.ca, self.args.server+":"+self.args.port)
        conf = client.get_config_file()
        if 'acls_in' in conf['dps'][network]['interfaces'][ofport]:
            vm_options.append("portacl: "+','.join(conf['dps'][network]['interfaces'][ofport]['acls_in']))
        if self.DOVESNAP_MIRROR in conf['dps'][network]['interfaces'] and 'mirror' in conf['dps'][network]['interfaces'][self.DOVESNAP_MIRROR] and ofport in conf['dps'][network]['interfaces'][self.DOVESNAP_MIRROR]['mirror']:
            vm_options.append("mirror: true")
        return '\n'.join(vm_options)

    def _scrape_external_iface(self, name):
        desc = [name, "", "External Interface"]
        iface = subprocess.check_output(['ifconfig', name])
        ether = iface.decode('utf-8').split('\n')[1]
        mac = ether.split()[1]
        desc.append(mac)
        return '\n'.join(desc)

    def _network_lookup(self, name):
        lookup = subprocess.check_output(['nslookup', name])
        hostname, address = lookup.decode('utf-8').split('\n')[4:-2]
        hostname = hostname.split('\t')[1]
        address = address.split(': ')[1]
        return hostname, address

    def _scrape_vm_iface(self, name):
        desc = ["", "Virtual Machine", name]
        vm_list = subprocess.check_output(['virsh', 'list'])
        vm_names = vm_list.decode('utf-8').split('\n')[2:-2]
        for vm_list in vm_names:
            vm_name = vm_list.split()[1]
            vm_iflist = subprocess.check_output(['virsh', 'domiflist', vm_name])
            ifaces = vm_iflist.decode('utf-8').split('\n')[2:-2]
            for iface in ifaces:
                mac = iface.split()[4]
                iface = iface.split()[0]
                if iface == name:
                    hostname, address = self._network_lookup(vm_name)
                    desc.insert(0, hostname)
                    desc.append(mac)
                    desc.append(f'{address}/24')
        return '\n'.join(desc)

    def _get_matching_lines(self, lines, re_str):
        match_re = re.compile(re_str)
        matching_lines = []
        for line in lines:
            match = match_re.match(line.decode('UTF-8'))
            if match:
                matching_lines.append(match)
        return matching_lines

    def _scrape_container_iface(self, name):
        lines = self._scrape_container_cmd(name, ['ip', '-o', 'link', 'show'])
        matching_lines = self._get_matching_lines(
            lines, r'^(\d+):\s+([^\@]+)\@if(\d+):.+link\/ether\s+(\S+).+$')
        results = []
        for match in matching_lines:
            iflink = int(match[1])
            ifname = match[2]
            peeriflink = int(match[3])
            mac = match[4]
            results.append((ifname, mac, iflink, peeriflink))
        return results

    def _scrape_container_ip(self, name, iflink):
        lines = self._scrape_container_cmd(name, ['ip', '-o', 'addr'])
        matching_lines = self._get_matching_lines(lines, r'^%u:.+inet\s+(\S+).+$' % iflink)
        for match in matching_lines:
            return match[1]
        return None

    def _scrape_bridge_ports(self, bridgename):
        lines = self._scrape_ovs(['ovs-ofctl', 'dump-ports-desc', bridgename])
        matching_lines = self._get_matching_lines(
            lines, r'^\s*(\d+|LOCAL)\((\S+)\).+$')
        port_desc = {}
        for match in matching_lines:
            port = match[1]
            desc = match[2]
            if port == 'LOCAL':
                port = self.OFP_LOCAL
            port = int(port)
            port_desc[desc] = port
        return port_desc

    def _scrape_all_bridge_ports(self):
        all_port_desc = {}
        lines = self._scrape_ovs(['ovs-vsctl', 'list-br'])
        matching_lines = self._get_matching_lines(
            lines, r'^(\S+)$')
        for match in matching_lines:
            bridgename = match[0]
            all_port_desc[bridgename] = self._scrape_bridge_ports(bridgename)
        return all_port_desc

    def _scrape_container_veths(self):
        container_veths = {}
        process = subprocess.Popen(
            ['ip', '-o', 'link', 'show', 'type', 'veth'], stdout=subprocess.PIPE)
        matching_lines = self._get_matching_lines(
            process.stdout.readlines(),
            r'^(\d+):\s+([^\@]+)\@.+link\/ether\s+(\S+).+link-netnsid\s+(\d+).*$')
        for match in matching_lines:
            iflink = int(match[1])
            ifname = match[2]
            mac = match[3]
            container_veths[iflink] = (ifname, mac)
        return container_veths

    def _scrape_patch_veths(self):
        patch_veths = {}
        process = subprocess.Popen(
            ['ip', '-o', 'link', 'show', 'type', 'veth'], stdout=subprocess.PIPE)
        matching_lines = self._get_matching_lines(
            process.stdout.readlines(),
            r'^\d+:\s+(%s[^\@]+)\@([^\:\s]+).+link\/ether\s+(\S+).+$' % self.PATCH_PREFIX)
        for match in matching_lines:
            ifname = match[1]
            peerifname = match[2]
            mac = match[3]
            patch_veths[ifname] = (peerifname, mac)
        assert len(patch_veths) % 2 == 0
        return patch_veths

    def _get_network_mode(self, network):
        return network['Options'].get('ovs.bridge.mode', 'flat')

    def _get_lb_port(self, network):
        return network['Options'].get('ovs.bridge.lbport', self.DOVESNAP_MIRROR)

    def _get_container_args(self, container_inspect):
        args = {}
        for arg_str in container_inspect['Config']['Cmd']:
            arg_str = arg_str.lstrip('-')
            arg_l = arg_str.split('=')
            if len(arg_l) > 1:
                args[arg_l[0]] = arg_l[1]
            else:
                args[arg_l[0]] = ""
        return args

    def build_graph(self):
        dot = Digraph()
        client = docker.APIClient(base_url=self.DOCKER_URL)
        if not client.ping():
            raise GraphDovesnapException('cannot connect to docker')
        dovesnap = self._get_named_container(client, self.DOVESNAP_NAME)
        if not dovesnap:
            raise GraphDovesnapException('cannot find dovesnap container')
        dovesnap_inspect = client.inspect_container(dovesnap['Id'])
        dovesnap_args = self._get_container_args(dovesnap_inspect)
        networks = self._get_dovesnap_networks(client)
        container_veths = self._scrape_container_veths()
        patch_veths = self._scrape_patch_veths()
        all_port_desc = self._scrape_all_bridge_ports()
        unresolved_links = []
        network_id_name = {}
        for network in networks:
            network_id = network['Id']
            network_name = network['Name']
            network = client.inspect_network(network_id)
            bridgename = self._dovesnap_bridgename(network_id)
            options = ['%s: %s' % (option.split('.')[-1], optionval)
                for option, optionval in network['Options'].items()]
            network_label = '\n'.join([network_name, bridgename] + options)
            network_id_name[bridgename] = network_id
            dot.node(network_id, network_label)
            container_ports = set()
            for container_id, container in network['Containers'].items():
                container_name = container['Name']
                container_inspect = client.inspect_container(container_id)
                for ifname, mac, iflink, peeriflink in self._scrape_container_iface(container_name):
                    if peeriflink in container_veths:
                        br_ifname, _ = container_veths[peeriflink]
                        labels = ['%s: %s' % (label.split('.')[-1], labelval)
                            for label, labelval in container_inspect['Config']['Labels'].items()]
                        host_label = [container_name, "", "Container", ifname, mac]
                        ip = self._scrape_container_ip(container_name, iflink)
                        if ip:
                            host_label.append(ip)
                        host_label.extend(labels)
                        ofport = all_port_desc[bridgename][br_ifname]
                        container_ports.add(ofport)
                        edge_label = '%u' % ofport
                        dot.node(container_id, '\n'.join(host_label))
                        dot.edge(network_id, container_id, edge_label)
                        break
            mode = self._get_network_mode(network)
            for br_desc, ofport in all_port_desc[bridgename].items():
                if ofport in container_ports:
                    continue
                if ofport == self.OFP_LOCAL:
                    if mode == 'nat':
                        dot.edge(network_id, 'NAT')
                elif br_desc in patch_veths:
                    unresolved_links.append((bridgename, br_desc, ofport))
                else:
                    if br_desc.startswith(self.VM_PREFIX):
                        vm_desc = self._scrape_vm_iface(br_desc)
                        vm_options = self._get_vm_options(network['Name'], ofport)
                        vm_desc += '\n'+vm_options
                        dot.node(br_desc, vm_desc)
                    else:
                        external_desc = self._scrape_external_iface(br_desc)
                        dot.node(br_desc, external_desc)
                    dot.edge(network_id, br_desc, str(ofport))

        non_container_bridges = set()

        # wire up links to non container bridges.
        for bridgename, br_desc, ofport in unresolved_links:
            network_id = network_id_name[bridgename]
            peer_br_desc = patch_veths[br_desc][0]
            for peer_bridgename, port_desc in all_port_desc.items():
                if peer_br_desc in port_desc:
                    peer_ofport = port_desc[peer_br_desc]
                    dot.edge(network_id, peer_bridgename, '%u : %u' % (ofport, peer_ofport))
                    if peer_bridgename not in network_id_name:
                        non_container_bridges.add(peer_bridgename)
                    break

        # resolve any remaining ports, on non container bridges.
        for bridgename in non_container_bridges:
            for br_desc, ofport in all_port_desc[bridgename].items():
                if ofport == self.OFP_LOCAL:
                    continue
                if br_desc in patch_veths:
                    continue
                if br_desc == dovesnap_args.get('mirror_bridge_in', ''):
                    dot.edge(br_desc, bridgename, str(ofport))
                else:
                    dot.edge(bridgename, br_desc, str(ofport))

        dot.format = 'png'
        dot.render(self.OUTPUT_FILE)
        # leave only PNG
        os.remove(self.OUTPUT_FILE)

def main():
    parser = argparse.ArgumentParser(
        description='Dovesnap Graph - A dot file output graph of VMs, containers, and networks controlled by Dovesnap')
    parser.add_argument('--ca', '-a', default='/opt/faucetconfrpc/faucetconfrpc-ca.crt',
                        help='FaucetConfRPC server certificate authority file')
    parser.add_argument('--cert', '-c', default='/opt/faucetconfrpc/faucetconfrpc.crt',
                        help='FaucetConfRPC server cert file')
    parser.add_argument('--key', '-k', default='/opt/faucetconfrpc/faucetconfrpc.key',
                        help='FaucetConfRPC server key file')
    parser.add_argument('--port', '-p', default='59999',
                        help='FaucetConfRPC server port')
    parser.add_argument('--server', '-s', default='faucetconfrpc',
                        help='FaucetConfRPC server name')
    args = parser.parse_args()
    g = GraphDovesnap(args)
    g.build_graph()


if __name__ == "__main__":
    main()