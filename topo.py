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
		self.generate(num_ports)

	def generate(self, num_ports):

		# TODO: code for generating the fat-tree topology
		k = num_ports #the main k value
		half_k = k // 2

		num_core_switches = half_k ** 2 #(k/2)^2 k-port core switches
		core_switches = {}
		agg_switches = {}

		host_num = 1

		#Looping over pods
		for pod in range(k):
			mapper_pod_agg = []
			mapper_pod_edge = []

			for switch in range(half_k,k):
				# the nomenclature below is implemented also to solve the multiple request issue faced at ryu when s1, a1 or e1 was implemented earlier with errors
				agg_switch = Node(id = f"a{pod:03d}{switch:03d}001", type="aggregation_switch") #nomenclature adherering to al-fares' paper stripped of special characters
				agg_switch.ip_address = f"10.{pod}.{switch}.1"
				self.switches.append(agg_switch)
				agg_switches[(pod, switch)] = agg_switch
				mapper_pod_agg.append(agg_switch)
			
			for switch in range(half_k):
				edge_switch = Node(id = f"e{pod:03d}{switch:03d}001", type="edge_switch")
				edge_switch.ip_address = f"10.{pod}.{switch}.1"
				self.switches.append(edge_switch)
				mapper_pod_edge.append(edge_switch)

				for host_id in range(2, half_k + 2):
					host = Node(id = f"h{host_num}", type="host")
					host.ip_address = f"10.{pod}.{switch}.{host_id}"
					self.servers.append(host)
					edge_switch.add_edge(host) #connecting edge switches to hosts
					host_num += 1
				
			for agg in mapper_pod_agg:
				for edge in mapper_pod_edge:
					edge.add_edge(agg) #connecting edge and aggregation switches

		
		#Instantiate core switches as per the paper
		for j in range(1,half_k+1):
			for i in range(1, half_k+1):
				core_switch = Node(id = f"s{k:03d}{j:03d}{i:03d}", type="core_switch")
				core_switch.ip_address = f"10.{k}.{j}.{i}"

				core_switches[(j,i)] = core_switch
				self.switches.append(core_switch)
				#map core to agg here

				map_agg_index = j - 1 + half_k #this is the target index for aggregation switch to map to core switch
				for pod in range(k):
					map_agg_switch = agg_switches[(pod, map_agg_index)]
					core_switch.add_edge(map_agg_switch)


