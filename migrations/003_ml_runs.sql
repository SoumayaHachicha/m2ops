CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    run_date TEXT NOT NULL,
    date_debut TEXT NOT NULL,
    date_fin TEXT NOT NULL,
    nombre_articles INTEGER NOT NULL,
    n_clusters INTEGER NOT NULL,
    model_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    artefacts_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS themes (
    run_id TEXT NOT NULL,
    theme_id TEXT NOT NULL,
    nom TEXT NOT NULL,
    mots_cles TEXT NOT NULL,
    taille INTEGER NOT NULL,
    PRIMARY KEY (run_id, theme_id)
);

CREATE TABLE IF NOT EXISTS articles_themes (
    run_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    theme_id TEXT NOT NULL,
    PRIMARY KEY (run_id, article_id)
);
