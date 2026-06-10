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

# Class for an edge in the graph
class Edge:
    def __init__(self):
        self.lnode = None
        self.rnode = None
    
    def remove(self):
        self.lnode.edges.remove(self)
        self.rnode.edges.remove(self)
        self.lnode = None
        self.rnode = None

# Class for a node in the graph
class Node:
    def __init__(self, id, type):
        self.edges = []
        self.id = id
        self.type = type

    # Add an edge connected to another node
    def add_edge(self, node):
        edge = Edge()
        edge.lnode = self
        edge.rnode = node
        self.edges.append(edge)
        node.edges.append(edge)
        return edge

    # Remove an edge from the node
    def remove_edge(self, edge):
        self.edges.remove(edge)

    # Decide if another node is a neighbor
    def is_neighbor(self, node):
        for edge in self.edges:
            if edge.lnode == node or edge.rnode == node:
                return True
        return False


class Fattree:

    def __init__(self, num_ports):
        self.servers = []
        self.switches = []
        self.core_switches = []
        self.agg_switches = []
        self.edge_switches = []
        self.generate(num_ports)

    def generate(self, num_ports):
        # TODO: code for generating the fat-tree topology		
        k = num_ports
        num_hosts = (k**3) // 4
        num_core = (k // 2) ** 2

        for i in range(num_hosts):
            host = Node(f"h{i}", "host")
            self.servers.append(host) 
        
        for i in range(num_core):
            switch = Node(f"c{i}", "core")
            self.core_switches.append(switch)
        
        for pod in range(k):
            for i in range(k // 2):
                agg = Node(f"a{pod}{i}", "agg")
                self.agg_switches.append(agg)

            for i in range(k // 2):
                edge = Node(f"e{pod}{i}", "edge")
                self.edge_switches.append(edge)
        
        self.switches = self.core_switches + self.agg_switches + self.edge_switches

        for edge in self.edge_switches:
            print(edge.id)

        for server in self.servers:
            print(server.id)

        for agg in self.agg_switches:
            print(agg.id)        

        # Connect edge switches to hosts
        for i, edge in enumerate(self.edge_switches):
            for j in range(k // 2):
                host_index = (i * (k // 2)) + j
                edge.add_edge(self.servers[host_index])

        # Connect agg switches to edge switches
        for i, agg in enumerate(self.agg_switches):
            pod = i // (k // 2)
            for j in range(k // 2):
                edge_index = (pod * (k // 2)) + j
                agg.add_edge(self.edge_switches[edge_index])
                
        # Connect core switches to agg switches
        for i, core in enumerate(self.core_switches):
            for j in range(k):
                agg_index = (j * (k // 2)) + (i // (k // 2))
                core.add_edge(self.agg_switches[agg_index])

        


        

        
        



            