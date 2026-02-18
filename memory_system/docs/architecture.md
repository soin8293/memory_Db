# OpenClaw Memory System Architecture

## Overview
The OpenClaw memory system is a hybrid storage architecture that combines traditional file-based storage with a custom vector database using embeddings for semantic search. This dual approach provides both reliable persistence and powerful semantic retrieval capabilities.

## Core Architecture

### 1. Hybrid Storage Layers

```
┌─────────────────────────────────────────┐
│        Vector Database (Embeddings)     │
│     - Semantic search capability        │
│     - High-dimensional vectors          │
│     - Similarity-based retrieval        │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│         File System Layer               │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │       MEMORY.md                   │  │
│  │ (Curated Long-term Memory)       │  │
│  │ Identity, Preferences, Objectives │  │
│  └───────────────────────────────────┘  │
│                    │                    │
│  ┌───────────────────────────────────┐  │
│  │     Daily Memory Files            │  │
│  │  memory/YYYY-MM-DD.md            │  │
│  │      (Raw Event Logs)            │  │
│  └───────────────────────────────────┘  │
│                    │                    │
│  ┌───────────────────────────────────┐  │
│  │    Structured Memory Nodes        │  │
│  │    memory/nodes.jsonl            │  │
│  │  (Append-only Indexed Data)      │  │
│  └───────────────────────────────────┘  │
│                    │                    │
│  ┌───────────────────────────────────┐  │
│  │      Project Memories             │  │
│  │  memory/projects/*.md            │  │
│  │   (Isolated Project Context)     │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### 2. Component Breakdown

#### A. Vector Database (Primary Semantic Layer)
- **Purpose**: Semantic search and similarity matching
- **Technology**: Custom vector database with embedding model
- **Content**: High-dimensional embeddings with metadata
- **Update Frequency**: Real-time during memory operations
- **Access Pattern**: Vector similarity search (ANN/KNN)

#### B. MEMORY.md (Executive Summary Layer)
- **Purpose**: Curated, executive-summary memory
- **Size**: Small (~2000 characters max)
- **Content**: Identity, preferences, active objectives, current constraints
- **Update Frequency**: Rare, only for durable information
- **Access Pattern**: High-frequency reads

#### C. Daily Memory Files (Raw Log Layer)
- **Purpose**: Temporary storage for daily events
- **Format**: YYYY-MM-DD.md
- **Content**: Raw conversations, decisions, actions
- **Lifecycle**: Ephemeral, eventually distilled
- **Access Pattern**: Sequential writes, occasional reads

#### D. Memory Nodes (Structured Data Layer)
- **Purpose**: Searchable, structured memory items (backup to vector DB)
- **Format**: Append-only JSONL format
- **Content**: Discrete, indexed memory pieces
- **Indexing**: memory/index.json for fast file retrieval
- **Access Pattern**: Indexed searches

#### E. Project Memories (Isolated Context Layer)
- **Purpose**: Project-specific persistent context
- **Format**: Per-project Markdown files
- **Content**: Detailed project-specific information
- **Scope**: Isolated to specific project context
- **Access Pattern**: On-demand loading

## Runtime Architecture

### Policy Injection System
```
Incoming User Message
         ↓
Policy Analyzer (build_runtime_policy.sh)
         ↓
Selected Policy Categories (max 3)
         ↓
Context Injection → AI Model
```

### Memory Retrieval Pipeline (Dual Approach)
```
Query → Vector Search (Primary)
    ↓
Semantic Results from Vector DB
    ↓
Fallback to File Search if needed
    ↓
File-based Results (memory_search + memory_get)
    ↓
Combined Context Injection → AI Model
```

## Technical Architecture

### System Organization
```
/memory_system/
├── memory_guide.md          # Architecture documentation
├── README.md               # System overview
├── policy/
│   └── core.md             # Fundamental rules
├── tools/
│   └── build_runtime_policy.sh  # Policy injection
└── architecture.md         # This document

/memory/ (runtime, managed by system)
├── YYYY-MM-DD.md           # Daily logs
├── MEMORY.md              # Curated memory
├── nodes.jsonl            # Structured nodes
├── index.json             # Node routing
├── projects/
│   └── <slug>.md         # Project dossiers
└── projects_index.json    # Project routing

/vector_db/ (custom vector database)
├── embeddings.bin         # Binary vector storage
├── metadata.json          # Vector metadata
├── index.ivf              # Vector index
└── config.json            # Vector DB settings
```

## Design Patterns

### 1. Dual Storage Pattern
- **Vector Database**: For semantic search and relationship mapping
- **File System**: For structured backup and human-readable logs
- Ensures redundancy and multiple access methods

### 2. Append-Only Architecture (Nodes)
- Memory nodes are only appended, never modified
- Prevents corruption from concurrent writes
- Enables easy backup and recovery
- Facilitates indexing and search

### 3. Tiered Hygiene System
- Daily files: Automatic archival
- Nodes: Periodic compaction
- Curated memory: Manual curation
- Vector DB: Periodic optimization and cleanup

### 4. Lazy Loading
- Memory is loaded on-demand
- Large memory blocks are paginated
- Unused memory segments remain unloaded
- Optimizes context window usage

## Vector Database Architecture

### Embedding Pipeline
```
Raw Memory → Preprocessing → Embedding Model → Vector Storage
```

### Vector Schema
```json
{
  "id": "unique_identifier",
  "vector": [0.1, 0.3, -0.2, ...],  // n-dimensional embedding
  "metadata": {
    "timestamp": "ISO8601",
    "source": "conversation/session/project",
    "importance": 0-1 score,
    "category": "fact/conversation/decision",
    "context_window": "surrounding text"
  },
  "text": "original memory content"
}
```

### Search Algorithm
- **Primary**: Cosine similarity / KNN search in vector space
- **Secondary**: BM25-style search in file system
- **Hybrid**: Combine both results with weighted scoring

## Integration Architecture

### With AI Models
- Memory injection at conversation start from both systems
- Selective retrieval during conversations (vector first, file backup)
- Context window management considering both sources
- Performance optimization through caching

### With External Systems
- Vector database synchronization
- File system backup/export
- API endpoints for both memory systems
- Event-driven updates

## Scalability Features

### Vector Database Scaling
- Approximate nearest neighbor (ANN) for large datasets
- Sharding by time or topic domains
- Caching frequently accessed vectors
- Dimensionality reduction techniques

### File System Scaling
- Project memories can be distributed
- Node indexing supports sharding
- Daily logs can be archived to external storage

### Combined Scaling
- Load balancing between systems
- Asynchronous indexing for both
- Performance monitoring across layers

## Security Architecture

### Vector Database Security
- Encryption for vector storage
- Authentication for database access
- Access controls for memory retrieval
- Secure embedding generation pipeline

### File System Security
- File system permissions
- Encryption for sensitive data
- Audit trails for memory access
- Session isolation

### Combined Security
- Memory compartmentalization across both systems
- Automatic purging of temporary data
- Consent-based memory retention
- Data minimization principles

## Upgrade Path Architecture

### Vector Database Evolution
- Embedding model upgrades and re-embedding
- Vector index optimization
- Schema evolution for metadata
- Performance improvements

### File System Evolution
- Backward compatibility for older formats
- Migration scripts for format changes
- Graceful degradation for older versions

### Forward Compatibility
- Extensible vector schemas
- Flexible metadata system
- Plugin architecture for new features

This hybrid architecture provides both the reliability of file-based storage and the power of semantic search through vector embeddings, creating a robust foundation for persistent AI memory.