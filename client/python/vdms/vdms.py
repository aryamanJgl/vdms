#
# The MIT License
#
# @copyright Copyright (c) 2017 Intel Corporation
# @copyright Copyright (c) 2020 ApertureData Inc
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

#! /usr/bin/python
import struct
from threading import Thread
import itertools
from concurrent.futures import ThreadPoolExecutor
import sys
import os
import socket
import urllib
import time
import json
import re

# VDMS Protobuf import (autogenerated)
import queryMessage_pb2

class vdms(object):

    def __init__(self, cluster_config, cluster_info):
        self.dataNotUsed = []
        self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)

        # TCP_QUICKACK only supported in Linux 2.4.4+.
        # We use startswith for checking the platform following Python's
        # documentation:
        # https://docs.python.org/dev/library/sys.html#sys.platform
        if sys.platform.startswith('linux'):
            self.conn.setsockopt(socket.SOL_TCP, socket.TCP_QUICKACK, 1)

        self.connected = False
        self.last_response = ''
        #TODO: make these fields private
        self.cluster_config = cluster_config # Can take on values: 'replicate', 'shard'
        #TODO: CHECK FOR THE IMPOSED RANKING in cluster_info BEING UNIQUE
        cluster_info[1] = sorted(cluster_info[1], key = lambda x: x[1]) # sorting servers by rank
        self.cluster_info = cluster_info # 3-tuple of (hostname, port, rank)
        self.num_servers = len(cluster_info[1])
        # configures last_server to the top-ranked server as a default
        self.last_server = 0

    # SELECTOR FUNCTIONS START #
    def distributed_Add(self):
        """
        Helper function for dealing with Addxx queries in a distributed environment
        returns: List(int) ... of servers in the cluster to re-route Addxxx query to
        cluster_config == 'shard': Selects the server to re-route Addxxx query to via round-robin
        cluster_config == 'replicate': Sends Addxxx query to every server in the coluster
        """
        if self.cluster_config == "shard":
            out = (self.last_server+1) % self.num_servers
            self.last_server += 1
            return out

        elif self.cluster_config == "replicate":
            return range(1, self.num_servers+1)

    def distributed_Search(self, searchQuery):
        """
        Helper function for deaing with database search queries in a distributed  environment
        searchQuery: A clean search query in dictionary form
        returns: List(int) ... of servers in the cluster to run the Searchxx query over
        """
        #TODO: Add a hashing method for more efficient searches
        return range(1, self.num_servers+1)

    def distributed_Update(self, updateQuery):
        """
        Helper function for deaing with database search queries in a distributed environment
        updateQuery: A clean update query in dictionary form
        returns: List(int) ... of servers in the cluster to run the Updatexxx query over
        """
        #TODO: Add a hashing method for more efficiently narrowing down elements
        return range(1, self.num_servers+1)

    # SELECTOR FUNCTIONS END #

    def execute_set_sync(self, server_set, query, blob_array=[]):
        """
        Helper function for creating multiple threads for facilitating parallel
        execution of a query over a subset of servers in the cluster
        server_set: List[Int] The subset of the cluster to execute the commands over
        command: The command to be executed over the selected servers
        returns: List[Dict] (JSON-parsable)
        """
        #TODO: Should a process be used here instead to get the kind of behaviour that I need?
        # This might end up being really intensive and error-prone though, since it creates
        # a lot of processes
        pool = ThreadPoolExecutor(len(server_set))
        threads = list()
        # https://stackoverflow.com/a/58829816
        with ThreadPoolExecutor() as executor: # context manager for the threads created inside
            for server in server_set:
                # Executing the threads
                arr = [(self.cluster_info[1][server][0], self.cluster_info[1][server][1]), query, blob_array]
                # https://github.com/Joldnine/joldnine.github.io/issues/10
                threads.append(executor.submit(lambda p: self.conn_send_receive(*p), arr))
        # for i, server in enumerate(server_set):
        #     # Constructing the threads, and storing them in a dict for easy access
        #     threads["t" + str(i)] = Thread(target=self.conn_send_receive,
        #                                    args=((self.cluster_info[1][server][0],
        #                                           self.cluster_info[1][server][1]), query, blob_array))
        # def mutate_dict(f,d):
        #     for k, v in d.iteritems():
        #         d[k] = f(v)
        # out_dict = mutate_dict(lambda x: x.start(), threads)

        return threads

    def conn_send_receive(self, conn_prop, query, blob_array=[]):
        """
        Target function for the threads to be executed in execute_set_sync
        Connects to a given server, sends the given query to it and recieves
        a response
        conn_prop: (hostname, port)
        query: List[Dict] (JSON-parsable)
        """
        self.connect(conn_prop)

        # Check the query type
        if not isinstance(query, str): # assumes json
            query_str = json.dumps(query)
        else:
            query_str = query

        if not self.connected:
            return "NOT CONNECTED"

        quer = queryMessage_pb2.queryMessage()
        # quer has .json and .blob
        quer.json = query_str

        # We allow both a "list of lists" or a "list"
        # to be passed as blobs.
        # This is because we originally forced a "list of lists",
        # for no good reason other than lacking Python skills.
        # But most of the apps pass a "list of list" as a param,
        # and we don't want to break backward-compatibility.
        # So we now allow both.
        for im in blob_array:
            if isinstance(im, list):
                # extend will insert the entire list at the end
                quer.blobs.extend(im)
            else:
                # append will just insert a single element at the end
                quer.blobs.append(im)

        # Serialize with protobuf and send
        data = quer.SerializeToString();
        sent_len = struct.pack('@I', len(data)) # send size first
        self.conn.send( sent_len )
        self.conn.send(data)

        # Recieve response
        #TODO: replace with recv(self.num_servers)
        recv_len = self.conn.recv(4)
        recv_len = struct.unpack('@I', recv_len)[0]
        response = b''
        while len(response) < recv_len:
            packet = self.conn.recv(recv_len - len(response))
            if not packet:
                return None
            response += packet

        querRes = queryMessage_pb2.queryMessage()
        querRes.ParseFromString(response)

        response_blob_array = []
        for b in querRes.blobs:
            response_blob_array.append(b)

        self.last_response = json.loads(querRes.json)

        self.disconnect()

        return (self.last_response, response_blob_array)


    @staticmethod
    def parse_query(query, commandName):
        #TODO: Get rid of this method
        """
        Helper function for extracting instances of  particular command out of a large query in
        dict form
        query: JSON to be parsed (in List[Dict] format)
        commandName: refer https://github.com/IntelLabs/vdms/wiki/API-Description for the list
        of allowed commands
        returns: Tuple[Int, List[Dict]], 1/0 for informing if found/not found and the Dict composed of
        the specific instance of commandName in the query
        """
        #TODO: Add distinguishing parse for SimilaritySearch queries
        out = []
        exists = 0
        for command in query:
            if commandName in command.keys():
                exists = 1
                out.append(command)

        if out:
            return (True, out)
        else:
            return (False, [])

    def __del__(self):
        self.conn.close()

    # def get_server(self, rank):
    #     """
    #     takes: rank of server to be found
    #     returns: (hostname, port) for the required server
    #     """
    #
    #     return self.cluster_info[1][[index for (index, a_tuple) in enumerate(self.cluster_info[1]) if a_tuple[1]==rank][0]]
    #
    def connect(self, host='localhost', port=55555):
        self.conn.connect((host, port))
        self.connected = True

    def disconnect(self):
        self.conn.close()
        self.connected = False

    # Recieves a json struct as a string
    def query(self, query, blob_array = [], distribute=False):
        #TODO: Change the following to actually reflect all kinds of API calls
        pattern = re.compile("Add.+")
        AddCommands = [x for x in query if re.search(pattern, list(x.keys())[0])]

        pattern = re.compile("Search.+")
        SearchCommands= [x for x in query if re.search(pattern, list(x.keys())[0])]

        pattern = re.compile("Update.+")
        UpdateCommands= [x for x in query if re.search(pattern, list(x.keys())[0])]


        #TODO: Since we will always perform Add queries on a single machine, get rid of
        # all the unecessary list processing
        AddList = [self.execute_set_sync(self.distributed_Add, AddCommand, blob_array)
                   for AddCommand in AddCommands] # List[List[Dict]]
        AddList = list(itertools.chain.from_iterable(AddList)) # Simply adding together all add query outputs

        UpdateList = [self.execute_set_sync(self.distributed_Update, UpdateCommand, blob_array) for UpdateCommand in UpdateCommands]
        UpdateList = list(itertools.chain.from_iterable(UpdateList)) # Simply adding together all update query outs

        SearchList = [self.execute_set_sync(self.distributed_Search, SearchCommand, blob_array) for SearchCommand in SearchCommands]
        SearchList = list(itertools.chain.from_iterable(SearchList)) #TODO: Change way SimilaritySearch commands are combined

        #TODO: Process each of the above three lists to produce a unified response
        return AddList + UpdateList + SearchList

    def get_last_response(self):
        return self.last_response

    def get_last_response_str(self):
        return json.dumps(self.last_response, indent=4, sort_keys=False)

    def print_last_response(self):
        print(self.get_last_response_str())
