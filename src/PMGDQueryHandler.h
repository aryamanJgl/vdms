#pragma once

#include <map>
#include <mutex>
#include <vector>

#include "protobuf/pmgdMessages.pb.h" // Protobuff implementation
#include "jarvis.h"

namespace athena {
    // Instance created per worker thread to handle all transactions on a given
    // connection.
    class PMGDQueryHandler
    {
        // This class is instantiated by the server each time there is a new
        // connection. So someone needs to pass a handle to the graph db itself.
        Jarvis::Graph *_db;

        // Need this lock till we have concurrency support in JL
        // TODO: Make this reader writer.
        std::mutex *_dblock;

        Jarvis::Transaction *_tx;

        /// Map an integer ID to a Node (reset at the end of each transaction).
        std::map<int, Jarvis::Node *> mNodes;
        /// Map an integer ID to an Edge (reset at the end of each transaction).
        std::map<int, Jarvis::Edge *> mEdges;

        pmgd::protobufs::CommandResponse add_node(const pmgd::protobufs::AddNode &cn);
        void process_query(pmgd::protobufs::Command *cmd);

    public:
        PMGDQueryHandler(Jarvis::Graph *_db, std::mutex *mtx);

        // The vector here can contain just one JL command but will be surrounded by
        // TX begin and end. So just expose one call to the QueryHandler for
        // the request server
        void process_queries(std::vector<pmgd::protobufs::Command *> cmds);
    };
};
