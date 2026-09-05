#!/usr/bin/env python3
"""Generates src/jobwrapper/data/skill_taxonomy.json.

The taxonomy is what lets keyword extraction work with zero LLM calls: a curated set of
canonical skill terms with their aliases, so "Postgres", "PostgreSQL" and "psql" all collapse to
one keyword, and so a JD's " 5+ years of Golang" resolves against a profile that says "Go".
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "jobwrapper" / "data" / "skill_taxonomy.json"

# canonical: (category, [aliases...])
SKILLS: dict[str, tuple[str, list[str]]] = {
    # languages
    "Python": ("language", ["python3", "py", "cpython"]),
    "JavaScript": ("language", ["js", "ecmascript", "es6", "es2015", "vanilla js"]),
    "TypeScript": ("language", ["ts"]),
    "Java": ("language", ["java8", "java 11", "java 17", "core java"]),
    "Go": ("language", ["golang", "go lang"]),
    "Rust": ("language", ["rustlang"]),
    "C": ("language", ["c language", "ansi c"]),
    "C++": ("language", ["cpp", "c plus plus", "cxx", "c++17", "c++20"]),
    "C#": ("language", ["csharp", "c sharp", ".net c#"]),
    "Ruby": ("language", ["ruby on rails language"]),
    "PHP": ("language", ["php8"]),
    "Swift": ("language", ["swiftui language"]),
    "Kotlin": ("language", ["kotlin jvm"]),
    "Scala": ("language", []),
    "R": ("language", ["r language", "rstats"]),
    "MATLAB": ("language", ["matlab/simulink"]),
    "Perl": ("language", []),
    "Bash": ("language", ["shell", "shell scripting", "sh", "zsh", "bash scripting"]),
    "PowerShell": ("language", ["pwsh"]),
    "SQL": ("language", ["structured query language", "ansi sql"]),
    "Elixir": ("language", []),
    "Haskell": ("language", []),
    "Objective-C": ("language", ["objc"]),
    "Dart": ("language", []),
    "Lua": ("language", []),
    "Solidity": ("language", []),
    "VBA": ("language", ["visual basic"]),
    "Groovy": ("language", []),
    "Clojure": ("language", []),
    "Julia": ("language", []),
    # frontend
    "React": ("frontend", ["react.js", "reactjs", "react 18", "react hooks"]),
    "Next.js": ("frontend", ["nextjs", "next js"]),
    "Vue.js": ("frontend", ["vue", "vuejs", "vue 3"]),
    "Angular": ("frontend", ["angularjs", "angular 2+"]),
    "Svelte": ("frontend", ["sveltekit"]),
    "Redux": ("frontend", ["redux toolkit", "rtk"]),
    "HTML": ("frontend", ["html5", "semantic html"]),
    "CSS": ("frontend", ["css3", "scss", "sass", "less"]),
    "Tailwind CSS": ("frontend", ["tailwind", "tailwindcss"]),
    "Bootstrap": ("frontend", []),
    "Material UI": ("frontend", ["mui", "material-ui"]),
    "Webpack": ("frontend", []),
    "Vite": ("frontend", []),
    "jQuery": ("frontend", []),
    "Storybook": ("frontend", []),
    "Three.js": ("frontend", ["threejs", "webgl"]),
    "D3.js": ("frontend", ["d3", "d3js"]),
    "Accessibility": ("frontend", ["a11y", "wcag", "aria", "section 508"]),
    "Responsive Design": ("frontend", ["mobile-first", "responsive web design"]),
    # backend / frameworks
    "Node.js": ("backend", ["node", "nodejs"]),
    "Express": ("backend", ["express.js", "expressjs"]),
    "NestJS": ("backend", ["nest.js"]),
    "Django": ("backend", ["django rest framework", "drf"]),
    "Flask": ("backend", []),
    "FastAPI": ("backend", ["fast api"]),
    "Spring Boot": ("backend", ["spring", "springboot", "spring mvc"]),
    "Ruby on Rails": ("backend", ["rails", "ror"]),
    "Laravel": ("backend", []),
    "ASP.NET": ("backend", ["asp.net core", "dotnet", ".net", ".net core"]),
    "GraphQL": ("backend", ["apollo", "graph ql"]),
    "REST APIs": ("backend", ["rest", "restful", "rest api", "restful services", "web api"]),
    "gRPC": ("backend", ["grpc/protobuf", "protocol buffers", "protobuf"]),
    "WebSockets": ("backend", ["websocket", "socket.io"]),
    "Microservices": ("backend", ["microservice architecture", "service oriented architecture", "soa"]),
    "Celery": ("backend", []),
    "Sidekiq": ("backend", []),
    "OAuth": ("backend", ["oauth2", "oidc", "openid connect", "sso", "saml"]),
    "JWT": ("backend", ["json web token"]),
    # data
    "PostgreSQL": ("data", ["postgres", "psql", "pgsql"]),
    "MySQL": ("data", ["mariadb"]),
    "MongoDB": ("data", ["mongo", "mongodb atlas"]),
    "Redis": ("data", ["redis cache", "elasticache"]),
    "Elasticsearch": ("data", ["elastic", "opensearch", "elk"]),
    "Cassandra": ("data", ["scylladb"]),
    "DynamoDB": ("data", ["dynamo"]),
    "SQLite": ("data", []),
    "Oracle": ("data", ["oracle db", "pl/sql"]),
    "SQL Server": ("data", ["mssql", "t-sql", "microsoft sql server"]),
    "Snowflake": ("data", []),
    "BigQuery": ("data", ["google bigquery"]),
    "Redshift": ("data", ["amazon redshift"]),
    "Databricks": ("data", ["delta lake"]),
    "Spark": ("data", ["apache spark", "pyspark", "spark streaming"]),
    "Hadoop": ("data", ["hdfs", "mapreduce"]),
    "Kafka": ("data", ["apache kafka", "confluent", "kafka streams"]),
    "Airflow": ("data", ["apache airflow", "dag"]),
    "dbt": ("data", ["data build tool"]),
    "ETL": ("data", ["elt", "data pipeline", "data pipelines", "ingestion pipeline"]),
    "Data Modeling": ("data", ["dimensional modeling", "star schema", "data warehouse", "warehousing"]),
    "Pandas": ("data", ["pandas dataframe"]),
    "NumPy": ("data", ["numpy arrays"]),
    "Tableau": ("data", []),
    "Power BI": ("data", ["powerbi"]),
    "Looker": ("data", ["lookml"]),
    "Flink": ("data", ["apache flink"]),
    "Presto": ("data", ["trino", "athena"]),
    # ml / ai
    "Machine Learning": ("ml", ["ml", "statistical learning", "supervised learning"]),
    "Deep Learning": ("ml", ["neural networks", "dnn", "cnn", "rnn"]),
    "PyTorch": ("ml", ["torch", "pytorch lightning"]),
    "TensorFlow": ("ml", ["tf", "keras"]),
    "scikit-learn": ("ml", ["sklearn", "scikit learn"]),
    "NLP": ("ml", ["natural language processing", "text mining"]),
    "Computer Vision": ("ml", ["cv", "opencv", "image processing"]),
    "LLMs": ("ml", ["large language models", "gpt", "claude", "generative ai", "genai", "foundation models"]),
    "RAG": ("ml", ["retrieval augmented generation", "vector search", "embeddings"]),
    "Prompt Engineering": ("ml", ["prompting"]),
    "MLOps": ("ml", ["ml ops", "model deployment", "mlflow", "model serving"]),
    "Recommendation Systems": ("ml", ["recsys", "recommender"]),
    "A/B Testing": ("ml", ["ab testing", "experimentation", "split testing"]),
    "Statistics": ("ml", ["statistical analysis", "hypothesis testing", "regression analysis"]),
    "XGBoost": ("ml", ["lightgbm", "gradient boosting"]),
    "Hugging Face": ("ml", ["huggingface", "transformers library"]),
    "LangChain": ("ml", ["llamaindex"]),
    # cloud / infra
    "AWS": ("cloud", ["amazon web services", "ec2", "s3", "lambda", "aws cloud"]),
    "Azure": ("cloud", ["microsoft azure", "azure cloud"]),
    "GCP": ("cloud", ["google cloud", "google cloud platform"]),
    "Docker": ("cloud", ["containers", "containerization", "dockerfile"]),
    "Kubernetes": ("cloud", ["k8s", "eks", "gke", "aks", "helm"]),
    "Terraform": ("cloud", ["hcl", "terraform cloud", "iac", "infrastructure as code"]),
    "Ansible": ("cloud", ["configuration management"]),
    "CI/CD": ("cloud", ["continuous integration", "continuous delivery", "continuous deployment", "build pipeline"]),
    "Jenkins": ("cloud", []),
    "GitHub Actions": ("cloud", ["gh actions"]),
    "GitLab CI": ("cloud", ["gitlab pipelines"]),
    "CircleCI": ("cloud", []),
    "ArgoCD": ("cloud", ["gitops", "flux"]),
    "Prometheus": ("cloud", ["grafana", "metrics", "alertmanager"]),
    "Datadog": ("cloud", ["new relic", "splunk", "observability", "apm"]),
    "Nginx": ("cloud", ["reverse proxy", "load balancing"]),
    "Linux": ("cloud", ["unix", "ubuntu", "centos", "rhel", "debian"]),
    "Serverless": ("cloud", ["lambda functions", "cloud functions", "faas"]),
    "CloudFormation": ("cloud", ["cdk", "aws cdk"]),
    "Pulumi": ("cloud", []),
    "Site Reliability Engineering": ("cloud", ["sre", "reliability engineering", "slo", "sli"]),
    # mobile
    "iOS": ("mobile", ["ios development", "uikit", "swiftui", "xcode"]),
    "Android": ("mobile", ["android sdk", "jetpack compose", "android studio"]),
    "React Native": ("mobile", ["rn"]),
    "Flutter": ("mobile", []),
    # practices / tools
    "Git": ("tools", ["github", "gitlab", "bitbucket", "version control", "source control"]),
    "Agile": ("practice", ["scrum", "kanban", "sprint planning", "agile methodology", "safe"]),
    "TDD": ("practice", ["test driven development", "test-driven"]),
    "Unit Testing": ("practice", ["pytest", "jest", "junit", "mocha", "unit tests", "testing"]),
    "Integration Testing": ("practice", ["e2e testing", "end-to-end testing", "cypress", "playwright", "selenium"]),
    "Code Review": ("practice", ["peer review", "pull requests", "pr review"]),
    "System Design": ("practice", ["distributed systems", "architecture design", "scalability", "high availability"]),
    "Performance Optimization": ("practice", ["performance tuning", "profiling", "latency optimization"]),
    "Security": ("practice", ["appsec", "application security", "owasp", "penetration testing", "secure coding"]),
    "Jira": ("tools", ["atlassian", "confluence"]),
    "Figma": ("tools", ["sketch", "adobe xd"]),
    "Postman": ("tools", ["insomnia", "api testing"]),
    "Excel": ("tools", ["microsoft excel", "spreadsheets", "google sheets", "pivot tables"]),
    "Salesforce": ("tools", ["sfdc", "apex"]),
    "SAP": ("tools", ["sap erp"]),
    "Stripe": ("tools", ["payments integration", "payment gateway"]),
    "Twilio": ("tools", []),
    "Segment": ("tools", ["amplitude", "mixpanel", "analytics instrumentation"]),
    # soft / leadership
    "Mentoring": ("soft", ["coaching", "mentorship", "onboarding engineers"]),
    "Technical Leadership": ("soft", ["tech lead", "team lead", "leading a team"]),
    "Cross-functional Collaboration": ("soft", ["cross functional", "stakeholder management", "partnering with product"]),
    "Communication": ("soft", ["written communication", "verbal communication", "presentation skills"]),
    "Problem Solving": ("soft", ["analytical thinking", "critical thinking", "troubleshooting"]),
    "Ownership": ("soft", ["end-to-end ownership", "self-starter", "autonomy", "bias for action"]),
    "Documentation": ("soft", ["technical writing", "runbooks", "design docs"]),
    "Product Sense": ("soft", ["product thinking", "user empathy", "customer focus"]),
    "Project Management": ("soft", ["roadmap planning", "prioritization", "delivery management"]),
    "Hiring": ("soft", ["interviewing", "recruiting", "technical interviews"]),
}

SENIORITY = {
    "intern": ["intern", "internship", "co-op", "trainee"],
    "entry": ["entry level", "junior", "jr.", "graduate", "new grad", "associate", "i ", "level 1"],
    "mid": ["mid-level", "mid level", "software engineer ii", "engineer 2", "level 2", "intermediate"],
    "senior": ["senior", "sr.", "sr ", "engineer iii", "level 3", "lead engineer"],
    "staff": ["staff", "staff engineer", "senior staff", "level 5", "l5", "l6"],
    "principal": ["principal", "distinguished", "architect", "fellow"],
    "manager": ["manager", "engineering manager", "em", "head of", "director", "vp", "chief"],
}

EMPLOYMENT_TYPES = {
    "full_time": ["full time", "full-time", "permanent", "fte", "regular"],
    "part_time": ["part time", "part-time"],
    "contract": ["contract", "contractor", "c2c", "w2 contract", "freelance", "consultant"],
    "internship": ["internship", "intern", "co-op", "summer analyst"],
    "temporary": ["temporary", "temp", "seasonal"],
}

WORK_MODEL = {
    "remote": ["remote", "work from home", "wfh", "fully remote", "distributed", "anywhere",
               "remote-first", "telecommute", "home-based"],
    "hybrid": ["hybrid", "flexible", "partially remote", "days in office", "hybrid remote"],
    "onsite": ["on-site", "onsite", "in office", "in-office", "on site", "office-based"],
}

SPONSORSHIP_NEGATIVE = [
    "no sponsorship", "not able to sponsor", "unable to sponsor", "cannot sponsor",
    "does not sponsor", "without sponsorship", "must be authorized to work without",
    "no visa sponsorship", "we are unable to provide sponsorship",
    "us citizens only", "citizenship required", "must be a us citizen",
    "security clearance required", "green card holders only",
]
SPONSORSHIP_POSITIVE = [
    "visa sponsorship available", "we sponsor", "sponsorship available", "h-1b sponsorship",
    "will sponsor", "open to sponsorship", "cap-exempt", "sponsorship provided",
]

alias_index: dict[str, str] = {}
for canonical, (_cat, aliases) in SKILLS.items():
    alias_index[canonical.lower()] = canonical
    for alias in aliases:
        alias_index[alias.lower()] = canonical

DATA = {
    "version": 2,
    "generated_by": "scripts/build_skill_taxonomy.py",
    "skills": {k: {"category": v[0], "aliases": v[1]} for k, v in SKILLS.items()},
    "alias_index": alias_index,
    "seniority": SENIORITY,
    "employment_types": EMPLOYMENT_TYPES,
    "work_model": WORK_MODEL,
    "sponsorship_negative": SPONSORSHIP_NEGATIVE,
    "sponsorship_positive": SPONSORSHIP_POSITIVE,
    "stopwords": [
        "the", "and", "for", "with", "you", "our", "are", "will", "have", "this", "that", "from",
        "your", "who", "all", "can", "not", "but", "any", "has", "was", "were", "been", "their",
        "work", "team", "role", "job", "company", "position", "candidate", "experience",
        "years", "ability", "strong", "excellent", "good", "great", "help", "including", "such",
        "well", "make", "need", "want", "like", "also", "more", "most", "other", "into", "about",
        "across", "within", "using", "used", "use", "new", "high", "best", "plus", "etc",
    ],
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(DATA, indent=2, ensure_ascii=False))
print(f"wrote {OUT}: {len(SKILLS)} canonical skills, {len(alias_index)} lookup terms")
