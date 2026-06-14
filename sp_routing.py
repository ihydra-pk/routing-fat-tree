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

class SPRouter(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SPRouter, self).__init__(*args, **kwargs)
        
        # Initialize the topology with #ports=4
        self.topo_net = topo.Fattree(4)
        self.host_map = {} # dpid, port and mac key-value pairs
        self.dp_map = {} #the datapaths and switches stored here dpid - datapath obj mapping
        self.dp_connectivity_map = {} #stores the out_port for every dpid to dpid connection 
        # format for dp_connectivity_map : [src_dpid][dst_dpid] = out_port
        self.switch_portmap = {} #stores port mapping of every switch: dpid = [ports]


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
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    # This function implements the Dijkstra's Shortest path algorithm
    def get_shortest_path(self, src_dpid, dst_dpid):
        distances = {map: float('inf') for map in self.dp_connectivity_map} #initialize distances dict with map's distance as inifinity by default
        distances[src_dpid] = 0 #initialize 0 for the source itself
        previous = {map: None for map in self.dp_connectivity_map}
        unvisited_nodes = set(self.dp_connectivity_map.keys())

        while unvisited_nodes:
            current_node = min(unvisited_nodes, key=lambda map: distances[map]) # finds the lowest distance from distances
            if distances[current_node] == float('inf') or current_node == dst_dpid:
                # handles infinity, deadends or destination and source match
                break
            unvisited_nodes.remove(current_node)

            for immediate_neighbor_node in self.dp_connectivity_map[current_node]:
                new_distance = distances[current_node] + 1 #treating every hop by 1 weight
                if new_distance < distances[immediate_neighbor_node]:
                    distances[immediate_neighbor_node] = new_distance #overwrite with lower distance
                    previous[immediate_neighbor_node] = current_node

        #backward path tracing here    
        shortest_path = []
        current_node = dst_dpid 
        while current_node is not None:
            shortest_path.append(current_node)
            current_node = previous[current_node]
        
        shortest_path.reverse() #reversing the backward path tracing to reveal the actual shortest path

        return shortest_path


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

        self.logger.info(f"message received {msg}")
        self.logger.info(f"Hostmap dictionary state: {self.host_map}")

        if arp.arp in [type(x) for x in data_packet.protocols]:
            self.logger.info("ARP packet received.")
            arp_proto = data_packet.get_protocols(arp.arp)[0]
            src_ip = arp_proto.src_ip
            dst_ip = arp_proto.dst_ip
            self.host_map[src_ip] = {'dpid': dpid, 'port': in_port, 'mac': src_mac}

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
            self.logger.info("IPV4 Packet received..")
            ipv4_proto = data_packet.get_protocols(ipv4.ipv4)[0]
            src_ip = ipv4_proto.src
            self.host_map[src_ip] = {'dpid': dpid, 'port': in_port, 'mac': src_mac}
            dst_ip = ipv4_proto.dst

            # ip response handling if present
            if dst_ip in self.host_map:
                dst_dpid = self.host_map[dst_ip]['dpid']
                dst_port = self.host_map[dst_ip]['port']

                if dpid == dst_dpid: #this condition satisfies the hosts being under same edge switch
                    match = parser.OFPMatch(eth_type=ETH_TYPE_IP, ipv4_dst=dst_ip)
                    actions = [parser.OFPActionOutput(dst_port)]

                    #add flow rule
                    self.add_flow(datapath, 1, match, actions)
                    datapath.send_msg(parser.OFPPacketOut(datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER, in_port=in_port, actions=actions, data=data_packet.data))
                    self.logger.info(f"IP response sent and flow rule added for destination {dst_ip}")
               
                else: # hosts won't be in either the same switch or pod, passing down to dikstra's
                    shortest_path = self.get_shortest_path(dpid, dst_dpid)
                    self.logger.info(f"Dijkstra's Algorithm Triggered, shortest path is {shortest_path}")
                    if shortest_path:
                        for i in range(len(shortest_path)):
                            switch_dpid = shortest_path[i]
                            node_datapath = self.dp_map[switch_dpid]
                            if switch_dpid == dst_dpid:
                                out_port = self.host_map[dst_ip]['port']
                            else:
                                next_switch_dpid = shortest_path[i+1]
                                out_port = self.dp_connectivity_map[switch_dpid][next_switch_dpid] #find out the out_port for intermdiate hops between shortest path switch list
                            
                            #add flow rule
                            match = parser.OFPMatch(eth_type=ETH_TYPE_IP, ipv4_dst=dst_ip)
                            actions = [parser.OFPActionOutput(out_port)]
                            self.add_flow(node_datapath, 10, match, actions)
                            self.logger.info(f"Flow rule added for shortest path datapath id {switch_dpid}")

                        #handle the first dropped packet
                        if len(shortest_path) > 1:
                            first_hop_dpid = shortest_path[1]
                            out_port = self.dp_connectivity_map[dpid][first_hop_dpid]
                        
                        else:
                            out_port = self.host_map[dst_ip]['port']
                        
                        actions = [parser.OFPActionOutput(out_port)]
                        if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                            out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=actions)
                        else:
                            out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data)

                        datapath.send_msg(out)
                        self.logger.info(f"initial packet forwarded out from {dpid} via port{out_port}")


            else:
                self.logger.info(f"IP reply not sent, can't find {dst_ip} in dictionary")
            
        
        else:
            self.logger.info("ignoring non-ipv4 or arp requests ...")
            return

        
