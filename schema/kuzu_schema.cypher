-- PaperMind KuzuDB Schema
-- Source: docs/architecture.md (verbatim)
-- 5 Node Tables + 10 Edge Tables

-- ═══════════════════════════════════════════════════════════════
-- NODE TABLES
-- ═══════════════════════════════════════════════════════════════

CREATE NODE TABLE Paper(
  paper_id   STRING,
  title      STRING,
  pub_year   INT64,
  venue      STRING,
  pdf_url    STRING,
  user_id    STRING,
  PRIMARY KEY (paper_id)
);

CREATE NODE TABLE Claim(
  claim_id         STRING,
  text             STRING,
  paper_id         STRING,
  section          STRING,
  page             INT64,
  support_count    INT64,
  contradict_count INT64,
  rgs_score        DOUBLE,
  support_density  DOUBLE,
  is_gap           BOOLEAN,
  PRIMARY KEY (claim_id)
);

CREATE NODE TABLE Method(
  node_id      STRING,
  name         STRING,
  paper_count  INT64,
  aliases      STRING[],
  PRIMARY KEY (node_id)
);

CREATE NODE TABLE Dataset(
  node_id  STRING,
  name     STRING,
  year     INT64,
  version  STRING,
  PRIMARY KEY (node_id)
);

CREATE NODE TABLE Author(
  author_id   STRING,
  name        STRING,
  affiliation STRING,
  PRIMARY KEY (author_id)
);

CREATE NODE TABLE Task(
  node_id     STRING,
  name        STRING,
  paper_count INT64,
  PRIMARY KEY (node_id)
);

-- ═══════════════════════════════════════════════════════════════
-- EDGE TABLES
-- ═══════════════════════════════════════════════════════════════

CREATE REL TABLE CITES(
  FROM Paper TO Paper,
  strength      INT64,
  cite_type     STRING,
  relation_role STRING
);

CREATE REL TABLE HAS_CLAIM(
  FROM Paper TO Claim,
  section STRING,
  page    INT64
);

CREATE REL TABLE CONTRADICTS(
  FROM Claim TO Claim,
  confidence  DOUBLE,
  evidence_a  STRING,
  evidence_b  STRING
);

CREATE REL TABLE SUPPORTS(
  FROM Claim TO Claim,
  confidence DOUBLE
);

CREATE REL TABLE USES_SAME_METHOD(
  FROM Paper TO Paper,
  method_name STRING,
  similarity  DOUBLE
);

CREATE REL TABLE PROPOSES(FROM Paper TO Method);
CREATE REL TABLE USES_DATASET(FROM Paper TO Dataset);
CREATE REL TABLE AUTHORED_BY(FROM Paper TO Author, ordering INT64);
CREATE REL TABLE REFERENCES(FROM Paper TO Claim);
CREATE REL TABLE APPLIES_TO(FROM Method TO Task);
