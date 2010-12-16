'''
Created on Dec 4, 2010

@author: mkiyer
'''
import logging
import heapq
import operator
import collections
import networkx as nx

from base import merge_strand, POS_STRAND, NEG_STRAND, NO_STRAND, INTRON, EXON, DUMMY
from cNode import Node

def imin2(x,y):
    return x if x <= y else y
def imax2(x,y):
    return x if x >= y else y

# constants for use as graph attributes
PLEN = 'plen'
PWT = 'pwt'
PSCORE = 'pscore'
PSRC = 'psrc'

def visit_node_from_parent(G, parent, child):    
    pnode = G.node[parent]
    cnode = G.node[child]
    # new path length is parent length + child length    
    parent_path_length = pnode.get(PLEN, 0)
    path_length = parent_path_length + (child.end - child.start)    
    # new path weight is minimum of parent weight (if exists) and child weight
    pcedge = G.edge[parent][child]
    if 'weight' in pcedge:
        child_weight = pcedge['weight']
        parent_weight = pnode.get(PWT, child_weight)  
    else:
        # if child does not have a 'weight' field use the
        # parent weight
        parent_weight = pnode[PWT]   
        child_weight = parent_weight
    path_weight = child_weight if child_weight < parent_weight else parent_weight
    # score if weight / length
    path_score = path_weight / path_length
    child_path_score = cnode.get(PSCORE, path_score)
    print 'visiting', parent, '->', child, 'len', path_length, 'wt', path_weight, 'score', path_score, 'child score', child_path_score
    if path_score >= child_path_score:
        # keep pointer to parent node that produced this high scoring path
        cnode = G.node[child]
        cnode[PLEN] = path_length
        cnode[PWT] = path_weight
        cnode[PSCORE] = path_score
        cnode[PSRC] = parent
        print 'wrote child', parent, '->', child, 'len', path_length, 'wt', path_weight, 'score', path_score

def clear_path_attributes(G):
    for n in G.nodes_iter():
        G.node[n] = {}

def find_best_path(G, sorted_edges, source, sink):
    '''
    use dynamic programming to find the highest scoring path through 
    the graph starting from 'source'
    '''
    # topologically sort nodes
    for parent, child in sorted_edges:
        visit_node_from_parent(G, parent, child)
    # traceback    
    path = [sink]
    attrdict = G.node[sink]
    score = attrdict[PSCORE]
    weight = attrdict[PWT]
    while path[-1] != source:
        path.append(G.node[path[-1]][PSRC])
    path.reverse()
    # clear path attributes
    for n in G.nodes_iter():
        nattrs = G.node[n]
        if PLEN in nattrs:
            del nattrs[PLEN]
            del nattrs[PWT]
            del nattrs[PSCORE]
            del nattrs[PSRC]
    return path, score, weight

def find_suboptimal_paths(G, start_node, end_node, 
                          fraction_major_path,
                          max_paths,
                          max_iters=10000):
    # topologically sort nodes
    sorted_nodes = nx.topological_sort(G)
    # get sorted edges of the sorted nodes
    sorted_edges = []
    for n in sorted_nodes:
        sorted_edges.extend((p,n) for p in G.predecessors(n))
    
    path, path_score, path_weight = find_best_path(G, sorted_edges, start_node, end_node)
    score_limit = path_score * fraction_major_path
    # enumerate paths until the score falls below the 
    # specified percentage of the best path
    while path_score >= score_limit:
        # subtract path weight from edge weights
        for parent,child in zip(path[:-1], path[1:]):
            pcedge = G.edge[parent][child]
            if 'weight' in pcedge:
                #print 'weight', parent, '->', child, pcedge['weight']  
                pcedge['weight'] -= path_weight
                #print 'weight after', pcedge['weight']
        #print 'path', path, path_score, path_weight
        yield path_score, path
        path, path_score, path_weight = find_best_path(G, sorted_edges, start_node, end_node)

def get_transcript_score_map(transcripts):
    # get transcript scores
    # TODO: could do this when originally reading in data
    id_score_map = {}
    for t in transcripts:
        # add scores to the score lookup table
        id_score_map[t.id] = t.score
        for e in t.exons:
            id_score_map[e.id] = e.score
    return id_score_map

def transform_graph(G, id_score_map):
    '''
    convert introns to weighted edges rather than nodes and
    use 'ids' attribute of nodes to retrieve scores for that
    node as well as overall node/edge weights    
    '''
    # create a new digraph
    H = nx.DiGraph()
    # add all nodes from previous graph
    for n,attr_dict in G.nodes_iter(data=True):
        # TODO: keep track of sample-specific scores
        if n.node_type == EXON:
            weight = sum(id_score_map[id] for id in attr_dict['ids'])
            #weight = 1.0e3 * count / float(n.end - n.start)
            H.add_node(n, weight=weight, ids=attr_dict['ids'])
    # add exon-exon edges
    for n,attr_dict in G.nodes_iter(data=True):
        if n.node_type == INTRON:
            weight = sum(id_score_map[id] for id in attr_dict['ids'])
            for pred in G.predecessors_iter(n):
                for succ in G.successors_iter(n):                    
                    H.add_edge(pred, succ, weight=weight, ids=attr_dict['ids'])
    return H

def get_start_and_end_nodes(G):
    # find graph strand
    strand = reduce(merge_strand, iter(n.strand for n in G.nodes_iter()))
    # find unique starting positions and their 
    # corresponding nodes in the subgraph
    tss_node_dict = collections.defaultdict(lambda: [])
    for n,d in G.in_degree_iter():
        if d == 0:
            tss_pos = n.end if strand == NEG_STRAND else n.start
            tss_node_dict[tss_pos].append(n)
    # add 'dummy' tss nodes if necessary
    dummy_start_nodes = []
    for tss_pos, tss_nodes in tss_node_dict.iteritems():
        dummy_start_node = Node(0, 0, NO_STRAND, DUMMY)
        dummy_start_nodes.append(dummy_start_node)
        #weight = sum(G.node[n]['weight'] for n in tss_nodes)
        #G.add_node(dummy_start_node, weight=weight, ids=[])
        G.add_node(dummy_start_node)
        for tss_node in tss_nodes:
            #G.add_edge(dummy_start_node, tss_node)            
            G.add_edge(dummy_start_node, tss_node, weight=G.node[tss_node]['weight'], ids=[])            
    # add a single 'dummy' end node
    end_nodes = [n for (n,d) in G.out_degree_iter()
                 if (d == 0)]
    dummy_end_node = Node(-1, -1, NO_STRAND, DUMMY)
    G.add_node(dummy_end_node)
    #G.add_node(dummy_end_node, weight=weight, ids=[])
    for end_node in end_nodes:
        G.add_edge(end_node, dummy_end_node)    
        #G.add_edge(end_node, dummy_end_node, weight=0, ids=[])    
    return dummy_start_nodes, dummy_end_node

def get_isoforms(G, transcripts,
                 fraction_major_path=0.15,
                 max_paths=5, 
                 max_iters=10000):                 
    # map transcript ids to scores
    id_score_map = get_transcript_score_map(transcripts)
    # replace intron nodes with exon-exon edges
    H = transform_graph(G, id_score_map)
    # partition graph into connected components
    gene_id = 0
    tss_id = 0
    logging.debug("PATHFINDER")
    for Hsubgraph in nx.weakly_connected_component_subgraphs(H):
        # add dummy start and end nodes to the graph
        dummy_start_nodes, dummy_end_node = get_start_and_end_nodes(Hsubgraph)
        for start_node in dummy_start_nodes:
            for score, path in find_suboptimal_paths(Hsubgraph, start_node, dummy_end_node, 
                                                     fraction_major_path=fraction_major_path,
                                                     max_paths=max_paths, 
                                                     max_iters=max_iters):
                # remove dummy nodes when returning path
                yield gene_id, tss_id, score, path[1:-1]
            tss_id += 1
        gene_id += 1
    logging.debug("/PATHFINDER")
