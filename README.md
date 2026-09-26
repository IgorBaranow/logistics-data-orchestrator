# Logistics Data Orchestrator

> **Note:** Anonymized snapshot of a production enterprise ETL pipeline. Proprietary credentials and internal routing logic are removed.

A concurrent, stateful ETL orchestrator for global data providers. Seamlessly integrates 7 APIs using advanced rate-limit evasion, dynamic payload parsing, and atomic SharePoint state management.

**Stack & Concepts:** Python 3.10+ | Pandas (Data Wrangling) | `concurrent.futures` (Multithreading) | REST APIs & OAuth2/JWT | OpenPyXL (Automated Reporting) | ETL Architecture | Schema Normalization | OneDrive/SharePoint Sync.

## Business Impact

* **Single Source of Truth:** Superseded the primary corporate enterprise system due to superior data accuracy and enriched context. It now serves as the central operational dashboard.
* **110+ Daily Active Users:** Empowers cross-functional teams to dynamically add columns and share data in real-time.
* **Zero Data Loss Automation:** Eliminated manual tracking. Seamlessly merges fresh API data with existing human comments without overwriting user state.

## Engineering Highlights

| Challenge | Architectural Solution | 
| :--- | :--- | 
| **Rate Limits & WAF Evasion** | Randomized payload queues, exponential backoff, and jitter across threads to bypass call limits. | 
| **Stateful Data Merging** | Parses live SharePoint XML to extract custom user columns/colors, merging them with fresh API data via `pandas`. | 
| **I/O Bottlenecks** | Uses `concurrent.futures.ThreadPoolExecutor` to poll 7 APIs simultaneously, cutting execution time. | 
| **Multi-Auth Complexity** | Natively handles diverse auth: `.pfx` certs, RSA decryption for JWTs (MSC), and auto-refreshing OAuth2. | 
| **Scalable OOP Design** | Built on a `BaseCarrier` abstract class enforcing strict contracts for HTTP sessions, retries, and JSON parsing. | 

## System Architecture

The core logic revolves around minimizing API costs via deduplication and safely re-merging stateful data.

```mermaid
graph TD
    %% Define Styles
    classDef input fill:#e1f5fe,stroke:#0288d1,stroke-width:2px,color:#000;
    classDef process fill:#fff3e0,stroke:#f57c00,stroke-width:2px,color:#000;
    classDef api fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#000;
    classDef output fill:#fce4ec,stroke:#c2185b,stroke-width:2px,color:#000;

    %% Nodes
    A1[Region A Input]:::input
    A2[Region B Input]:::input
    A3[Region C Input]:::input
    
    B[Aggregator & Deduplicator]:::process
    
    C1((API Provider X)):::api
    C2((API Provider Y)):::api
    C3((API Provider Z)):::api
    C4((+4 Others)):::api
    
    D[Data Merger & State Preservation]:::process
    E[(Live current SharePoint File\nwith User inputs)]:::input
    
    F[Final Dashboard]:::output
    G[Atomic Update\nSharePoint Upload]:::output

    %% Flow
    A1 --> B
    A2 --> B
    A3 --> B
    
    B -- Unique Records Only --> C1
    B -- Unique Records Only --> C2
    B -- Unique Records Only --> C3
    B -- Unique Records Only --> C4
    
    C1 --> D
    C2 --> D
    C3 --> D
    C4 --> D
    
    E -- Extract Custom Columns & Notes --> D
    
    D --> F
    F --> G
```

## Project Structure
```text
├── carriers/                 # Integration Layer (Abstract Base Class & API Implementations)
│   ├── base_carrier.py       # Core OOP logic (Auth, Retries, JSON Parsing, Exponential Backoff)
│   ├── provider_alpha.py     .
│   ├── provider_beta.py      
│   ├── provider_delta.py     
│   ├── provider_epsilon.py   
│   ├── provider_gamma.py     
│   ├── provider_omega.py     
│   └── provider_zeta.py      
├── certs/                    # Secure certificate storage
│   └── provider_cert.pfx     # Local certs
├── utils/                    # Core Business & Processing Logic
│   ├── __init__.py           
│   ├── constants.py          # Mappings and globally shared variables
│   ├── data_cleaner.py       # Pandas data wrangling & cross-departmental deduplication
│   ├── excel_writer.py       # Openpyxl dynamic schema generation & styling
│   ├── logger.py             # Rotating log configuration for production
│   └── sharepoint.py         # Atomic OS file ops & SharePoint state extraction
├── .env.example              # Environment variables template
├── .gitignore                
├── config.py                 # Environment configuration and pipeline routing
├── main.py                   # Multi-threaded orchestrator entry point
└── requirements.txt          
```
