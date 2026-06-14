"""
 Copyright (c) 2025 Computer Networks Group @ UPB

 Permission is hereby granted, free of charge, to any person obtaining a copy of
 this software and associated documentation files (the "Software"), to deal in
 the Software without restriction, including without limitation the rights to
 use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
 the Software, and to permit persons to whom the Software is furnished to do so,
 subject to the following conditions:

 The above copyright notice and this permission notice shall be included in all
 copies or substantial portions of the Software.

 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
 FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
 COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
 IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
 CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 """

#!/usr/bin/env python3

from ryu.base import app_manager
from ryu.controller import mac_to_port
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import packet
from ryu.lib.packet import ipv4
from ryu.lib.packet import arp, ethernet
from ryu.lib.packet.ether_types import ETH_TYPE_IPV6, ETH_TYPE_ARP, ETH_TYPE_IP, ETH_TYPE_LLDP
from ryu.topology import event, switches
from ryu.topology.api import get_switch, get_link
from ryu.app.wsgi import ControllerBase

import topo


class FTRouter(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(FTRouter, self).__init__(*args, **kwargs)
        
        # Initialize the topology with #ports=4
        self.k = 4
        self.half_k = self.k // 2
        self.topo_net = topo.Fattree(self.k)
        self.host_map = {} # dpid, port and mac key-value pairs
        self.dp_map = {} #the datapaths and switches stored here dpid - datapath obj mapping
        self.dp_connectivity_map = {} #stores the out_port for every dpid to dpid connection 
        # format for dp_connectivity_map : [src_dpid][dst_dpid] = out_port
        self.switch_portmap = {} #stores port mapping of every switch: dpid = [ports]
        self.dpid_info = {} #populated from topo_net
        self.alfares_switches_count = (5 * (self.k ** 2)) // 4

        for switch in self.topo_net.switches:
            mn_ryu_dpid = int(''.join(filter(str.isdigit, switch.id)))
            ip_parts = switch.ip_address.split('.')
            self.dpid_info[mn_ryu_dpid] = {
                'switch_type': switch.type,
                'pod': int(ip_parts[1]), # from the alfares' ip addressing convention finding the pod
                'switch_index': int(ip_parts[2]),
                'last_octet': int(ip_parts[3])
            }


    # Topology discovery
    @set_ev_cls(event.EventSwitchEnter)
    def get_topology_data(self, ev):

        # Switches and links in the network
        switches = get_switch(self, None)
        links = get_link(self, None)

                # self.logger.info(f"Switches data structure is: {switches} with length {len(switches)}")
        # self.logger.info(f"Switch object data structure is: {vars(switches[0])} with dp {vars(switches[0].dp)}")
        
        for switch in switches:
            self.dp_connectivity_map.setdefault(switch.dp.id, {}) #initialize empty dict for every dpid
            self.switch_portmap[switch.dp.id] = [
                port.port_no for port in switch.ports if port.port_no != 0xfffffffe # here 0xfffffffe is value of ofproto.OFPP_LOCAL- to filter it out
            ]
        # self.logger.info(f"Links data structure is: {links} with length {len(links)}")
        # [self.logger.info(f"Link: Switch {l.src.dpid} [Port {l.src.port_no}] >> Switch {l.dst.dpid} [Port {l.dst.port_no}]") for l in links]

        # the loop parses the get_links() output and populates the dp_connectivity map initialized above
        for link in links:
            src_dpid = link.src.dpid
            dst_dpid = link.dst.dpid
            out_port = link.src.port_no
            
            try:
                self.dp_connectivity_map[src_dpid][dst_dpid] = out_port
            except Exception as e:
                self.logger.info(f"error occured while adding links with error {e}")

        if len(self.dp_map) == self.alfares_switches_count and len(switches) == self.alfares_switches_count:
        #     for switch in switches:
        #         self.dpid_to_node[switch.dp.id] = self.topo_net.switches[]
            self.categorize_switches()
            self.install_2level_rule()
        else:
            self.logger.info(f"Waiting for categorization for full network connectivity with predetermined number of switches and links")

    def install_2level_rule(self):
        self.logger.info("Creating Static Fat-tree routing rules from the paper")
        for dpid, datapath in self.dp_map.items():
            if dpid not in self.dpid_info:
                continue

            parser = datapath.ofproto_parser
            # switch_type = self.dpid_info[dpid]['switch_type'] | using the categorization instead, this works too
            pod = self.dpid_info[dpid]['pod']
            switch_index = self.dpid_info[dpid]['switch_index']

            #write core switch rules after filter
            if dpid in self.core_switches:
                for neighbor_dpid, out_port in self.dp_connectivity_map[dpid].items():
                    neighbor_pod = self.dpid_info[neighbor_dpid]['pod']
                    match = parser.OFPMatch(eth_type=ETH_TYPE_IP, ipv4_dst=(f"10.{neighbor_pod}.0.0", "255.255.0.0")) # downward matching core /16 prefix
                    actions = [parser.OFPActionOutput(out_port)]
                    self.add_flow(datapath, priority=50, match=match, actions=actions)
            
            elif dpid in self.aggregation_switches:
                # host_suffix = 2 # in fat tree implementation, host ips start ending in .2 to k/2+1
                for neighbor_dpid, out_port in self.dp_connectivity_map[dpid].items():
                    if neighbor_dpid in self.edge_switches: #this is for downwards
                        neighbor_switch_index = self.dpid_info[neighbor_dpid]['switch_index']
                        match = parser.OFPMatch(eth_type=ETH_TYPE_IP, ipv4_dst=(f"10.{pod}.{neighbor_switch_index}.0", "255.255.255.0")) #prefix matching /24
                        actions = [parser.OFPActionOutput(out_port)]
                        self.add_flow(datapath, priority=100, match=match, actions=actions) #higher priority for prefix matching
                    
                    sorted_neighbors = sorted(self.dp_connectivity_map[dpid].keys())
                    #filter the relevant core ports from sorted ports
                    core_ports = [self.dp_connectivity_map[dpid][neighbor_dpid] for neighbor_dpid in sorted_neighbors if neighbor_dpid in self.core_switches]

                    for host_id in range(2, self.half_k + 2):
                        port_index = (host_id - 2 + switch_index) % self.half_k # formula from the paper for entropy
                        out_port = core_ports[port_index]
                        match = parser.OFPMatch(eth_type=ETH_TYPE_IP, ipv4_dst=(f"0.0.0.{host_id}", "0.0.0.255"))
                        actions = [parser.OFPActionOutput(out_port)]
                        self.add_flow(datapath, priority=50, match=match, actions=actions) #low priority for upwards


                    # if neighbor_dpid in self.core_switches: #for upwards
                    #     i_value = self.dpid_info[neighbor_dpid]['last_octet']
                    #     target_host_suffix = i_value + 1
                    #     match = parser.OFPMatch(eth_type=ETH_TYPE_IP, ipv4_dst=(f"0.0.0.{target_host_suffix}", "0.0.0.255")) #suffix matching last octet
                    #     actions = [parser.OFPActionOutput(out_port)]
                    #     self.add_flow(datapath, priority=50, match=match, actions=actions) #lower priority for upward suffix matching

            elif dpid in self.edge_switches:
                sorted_neighbors = sorted(self.dp_connectivity_map[dpid].keys())
                #filter the relevant agg ports from sorted ports
                agg_ports = [self.dp_connectivity_map[dpid][neighbor_dpid] for neighbor_dpid in sorted_neighbors if neighbor_dpid in self.aggregation_switches]

                # host_suffix = 2 # in fat tree implementation, host ips start ending in .2 to k/2+1
                for host_id in range(2, self.half_k + 2):
                    port_index = (host_id - 2 + switch_index) % self.half_k
                    out_port = agg_ports[port_index % len(agg_ports)]

                    match = parser.OFPMatch(eth_type=ETH_TYPE_IP, ipv4_dst=(f"0.0.0.{host_id}", "0.0.0.255"))
                    actions = [parser.OFPActionOutput(out_port)]
                    self.add_flow(datapath, priority=50, match=match, actions=actions)
                
                # for neighbor_dpid, out_port in self.dp_connectivity_map[dpid].items():
                #     if neighbor_dpid in self.aggregation_switches:
                #         aggregation_neighbor_index = self.dpid_info[neighbor_dpid]['switch_index']
                #         target_host_suffix = (aggregation_neighbor_index - self.half_k) + 2
                #         match = parser.OFPMatch(eth_type=ETH_TYPE_IP, ipv4_dst=(f"0.0.0.{target_host_suffix}","0.0.0.255"))
                #         actions = [parser.OFPActionOutput(out_port)]
                #         self.add_flow(datapath, priority=50, match=match, actions=actions)

                    # else: #these are hosts
                    #     continue




    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        dpid = datapath.id
        self.dp_map[dpid] = datapath #populate the dp map dictionary

        # Install entry-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    # Add a flow entry to the flow-table
    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Construct flow_mod message and send it
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    def categorize_switches(self):
        self.edge_switches = set()
        self.aggregation_switches = set()
        self.core_switches = set()

        for switch_dpid in self.dp_map:
            if switch_dpid not in self.switch_portmap:
                continue

            dp_link_ports = self.dp_connectivity_map[switch_dpid].values()
            dp_host_ports = [p for p in self.switch_portmap[switch_dpid] if p not in dp_link_ports]

            if len(dp_host_ports) > 0:
                self.edge_switches.add(switch_dpid)

        for switch_dpid in self.dp_map:
            if switch_dpid in self.edge_switches: #ignore the edge_switches here
                continue

            connected_neighbors = self.dp_connectivity_map.get(switch_dpid,{}).keys()

            if any(neighbor in self.edge_switches for neighbor in connected_neighbors):
                self.aggregation_switches.add(switch_dpid)
            else:
                self.core_switches.add(switch_dpid)

        # self.logger.info(f"Edge Switches: {self.edge_switches}")
        # self.logger.info(f"Agg Switches: {self.aggregation_switches}")
        # self.logger.info(f"Core Switches: {self.core_switches}")


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # TODO: handle new packets at the controller
        in_port = msg.match['in_port']
        data_packet = packet.Packet(msg.data)
        eth_proto = data_packet.get_protocol(ethernet.ethernet)
        src_mac = eth_proto.src


        ######  log/test area
        # self.logger.info(f"dp_map dictionary's current state: {self.dp_map}")
        # self.logger.info(f"switch_portmap dictionary's current state: {self.switch_portmap}")
        # self.logger.info(f"dp_connectivity_map dictionary's current state: {self.dp_connectivity_map}")


        #getting rid of ipv6 packet noise
        if eth_proto.ethertype == ETH_TYPE_IPV6:
            return
        #getting rid of lldp noise
        if eth_proto.ethertype == ETH_TYPE_LLDP:
            return

        # self.logger.info(f"message received {msg}")
        # self.logger.info(f"Hostmap dictionary state: {self.host_map}")

        if arp.arp in [type(x) for x in data_packet.protocols]:
            arp_proto = data_packet.get_protocols(arp.arp)[0]
            src_ip = arp_proto.src_ip
            dst_ip = arp_proto.dst_ip
            self.logger.info(f"ARP packet received from {src_ip} to {dst_ip}.")
            self.host_map[src_ip] = {'dpid': dpid, 'port': in_port, 'mac': src_mac}

            #pushing prefixmatch here for edge downwards
            edge_match = parser.OFPMatch(eth_type=ETH_TYPE_IP, ipv4_dst=src_ip)
            edge_actions = [parser.OFPActionOutput(in_port)]
            self.add_flow(datapath, priority=200, match=edge_match, actions=edge_actions)

            if arp_proto.opcode == arp.ARP_REQUEST:
                #arp request handling if present
                if dst_ip in self.host_map:
                    dst_mac = self.host_map[dst_ip]['mac']

                    #build response
                    response_packet = packet.Packet()

                    eth_proto_response = ethernet.ethernet(dst=src_mac,src=dst_mac, ethertype=ETH_TYPE_ARP)
                    arp_proto_response = arp.arp(opcode=arp.ARP_REPLY, src_mac=dst_mac,src_ip=dst_ip, dst_mac=src_mac, dst_ip=src_ip)
                    response_packet.add_protocol(eth_proto_response)
                    response_packet.add_protocol(arp_proto_response)
                    #conversion to binary
                    response_packet.serialize()

                    #define actions
                    # out_port = ofproto.OFPP_IN_PORT
                    out_port = in_port
                    actions = [parser.OFPActionOutput(out_port)]
                    #send final response
                    self.logger.info(f"Sending ARP response... with these actions: {actions}")
                    datapath.send_msg(parser.OFPPacketOut(datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER, in_port=ofproto.OFPP_CONTROLLER, actions=actions, data=response_packet.data))
                    self.logger.info(f"ARP reply sent to {src_ip} proxied as {dst_ip} has mac {dst_mac}")
                
                else:
                    self.logger.info(f"can't find {dst_ip} in dictionary, arp forwarding from all edge ports - targetted pseudoflooding")
                    pseudoflood_counter = 0
                    for switch_dpid, switch_object in self.dp_map.items():
                        if switch_dpid not in self.switch_portmap:
                            continue
                        # logic - subtracting switch-to-switch port from exhaustive list of ports to find out host ports in all switches
                        dp_link_ports = self.dp_connectivity_map[switch_dpid].values()
                        dp_host_ports = [p for p in self.switch_portmap[switch_dpid] if p not in dp_link_ports]

                        for host_port in dp_host_ports:
                            actions = [switch_object.ofproto_parser.OFPActionOutput(host_port)]
                            out = switch_object.ofproto_parser.OFPPacketOut(datapath=switch_object, buffer_id=ofproto.OFP_NO_BUFFER, in_port=switch_object.ofproto.OFPP_CONTROLLER, actions=actions, data=msg.data)
                            switch_object.send_msg(out)
                            pseudoflood_counter += 1
                            self.logger.info(f"[ARP REQ] === FROM SWITCH {switch_dpid} PORT {host_port}")
                    self.logger.info(f"arp sent to {pseudoflood_counter} ports for unknown dst")
            
            elif arp_proto.opcode == arp.ARP_REPLY:
                if dst_ip in self.host_map:
                    final_dpid = self.host_map[dst_ip]['dpid']
                    final_port = self.host_map[dst_ip]['port']
                    target_datapath = self.dp_map[final_dpid]
                    
                    actions = [parser.OFPActionOutput(final_port)]
                    out = parser.OFPPacketOut(datapath=target_datapath, buffer_id=ofproto.OFP_NO_BUFFER, in_port=ofproto.OFPP_CONTROLLER, actions=actions, data=msg.data) # Send the ARP reply
                    target_datapath.send_msg(out)
                    self.logger.info(f"ARP Reply forwarded from {src_ip} to {dst_ip}")

        
        elif ipv4.ipv4 in [type(x) for x in data_packet.protocols]:
            pass
        
        else:
            self.logger.info("ignoring non-ipv4 or arp requests ...")
            return
