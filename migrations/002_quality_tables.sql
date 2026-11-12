CREATE TABLE IF NOT EXISTS articles_propres (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    lien TEXT NOT NULL,
    titre TEXT,
    resume TEXT,
    publie_le TEXT,
    recupere_le TEXT,
    rubrique TEXT,
    payload TEXT NOT NULL,
    UNIQUE(source, lien)
);

CREATE TABLE IF NOT EXISTS rejets (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL,
    source TEXT NOT NULL,
    regle TEXT NOT NULL,
    raison TEXT NOT NULL,
    date_rejet TEXT NOT NULL
);
