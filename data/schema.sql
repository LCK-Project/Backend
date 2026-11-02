CREATE TABLE League (
    league_id INT PRIMARY KEY,
    league_name VARCHAR(100) NOT NULL,
    region VARCHAR(50),
    description TEXT
);

CREATE TABLE Champion (
    champion_id INT PRIMARY KEY,
    champion_name VARCHAR(50) NOT NULL,
    role_type VARCHAR(50),
    description TEXT
);

CREATE TABLE Team (
    team_id INT PRIMARY KEY,
    team_name VARCHAR(100) NOT NULL,
    region VARCHAR(50),
    founded_year INT,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE Player (
    player_id INT PRIMARY KEY,
    player_name VARCHAR(100) NOT NULL,
    real_name VARCHAR(100),
    position VARCHAR(50),
    nationality VARCHAR(50),
    birth_date DATE,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE TeamAlias (
    team_alias_id INT PRIMARY KEY,
    team_id INT,
    alias_name VARCHAR(100),
    alias_type VARCHAR(50),
    FOREIGN KEY (team_id) REFERENCES Team(team_id)
);

CREATE TABLE PlayerAlias (
    player_alias_id INT PRIMARY KEY,
    player_id INT,
    alias_name VARCHAR(100),
    alias_type VARCHAR(50),
    FOREIGN KEY (player_id) REFERENCES Player(player_id)
);

CREATE TABLE Tournament (
    tournament_id INT PRIMARY KEY,
    league_id INT,
    tournament_name VARCHAR(100) NOT NULL,
    season_year INT,
    split VARCHAR(20),
    start_date DATE,
    end_date DATE,
    FOREIGN KEY (league_id) REFERENCES League(league_id)
);

CREATE TABLE TeamRoster (
    roster_id INT PRIMARY KEY,
    team_id INT,
    player_id INT,
    start_date DATE,
    end_date DATE,
    role VARCHAR(50),
    is_current BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (team_id) REFERENCES Team(team_id),
    FOREIGN KEY (player_id) REFERENCES Player(player_id)
);

CREATE TABLE Match (
    match_id INT PRIMARY KEY,
    tournament_id INT,
    match_date DATETIME,
    team_a_id INT,
    team_b_int INT, -- typo fix: team_b_id
    team_b_id INT, 
    match_format VARCHAR(20),
    match_stage VARCHAR(50),
    winner_team_id INT,
    score_a INT DEFAULT 0,
    score_b INT DEFAULT 0,
    FOREIGN KEY (tournament_id) REFERENCES Tournament(tournament_id),
    FOREIGN KEY (team_a_id) REFERENCES Team(team_id),
    FOREIGN KEY (team_b_id) REFERENCES Team(team_id),
    FOREIGN KEY (winner_team_id) REFERENCES Team(team_id)
);

CREATE TABLE Game (
    game_id INT PRIMARY KEY,
    match_id INT,
    game_no INT,
    blue_team_id INT,
    red_team_id INT,
    winner_team_id INT,
    duration_seconds INT,
    FOREIGN KEY (match_id) REFERENCES Match(match_id),
    FOREIGN KEY (blue_team_id) REFERENCES Team(team_id),
    FOREIGN KEY (red_team_id) REFERENCES Team(team_id),
    FOREIGN KEY (winner_team_id) REFERENCES Team(team_id)
);

CREATE TABLE PlayerGameStat (
    player_game_stat_id INT PRIMARY KEY,
    game_id INT,
    player_id INT,
    team_id INT,
    champion_id INT,
    kills INT DEFAULT 0,
    deaths INT DEFAULT 0,
    assists INT DEFAULT 0,
    cs INT DEFAULT 0,
    gold INT DEFAULT 0,
    FOREIGN KEY (game_id) REFERENCES Game(game_id),
    FOREIGN KEY (player_id) REFERENCES Player(player_id),
    FOREIGN KEY (team_id) REFERENCES Team(team_id),
    FOREIGN KEY (champion_id) REFERENCES Champion(champion_id)
);

CREATE TABLE TeamGameStat (
    team_game_stat_id INT PRIMARY KEY,
    game_id INT,
    team_id INT,
    total_kills INT DEFAULT 0,
    total_deaths INT DEFAULT 0,
    dragons INT DEFAULT 0,
    barons INT DEFAULT 0,
    towers INT DEFAULT 0,
    total_gold INT DEFAULT 0,
    FOREIGN KEY (game_id) REFERENCES Game(game_id),
    FOREIGN KEY (team_id) REFERENCES Team(team_id)
);

-- 4. 기사 및 근거 데이터 (소스 레이어)
CREATE TABLE Article (
    article_id INT PRIMARY KEY,
    news_id VARCHAR(100),
    title VARCHAR(500) NOT NULL,
    content TEXT,
    published_at DATETIME,
    provider VARCHAR(100),
    byline VARCHAR(100),
    url VARCHAR(1000)
);

CREATE TABLE ArticleChunk (
    chunk_id INT PRIMARY KEY,
    article_id INT,
    chunk_order INT,
    chunk_text TEXT,
    FOREIGN KEY (article_id) REFERENCES Article(article_id)
);

CREATE TABLE SourceEvidence (
    evidence_id INT PRIMARY KEY,
    article_id INT,
    chunk_id INT,
    target_table VARCHAR(50),
    target_id INT,
    evidence_text TEXT,
    confidence FLOAT,
    FOREIGN KEY (article_id) REFERENCES Article(article_id),
    FOREIGN KEY (chunk_id) REFERENCES ArticleChunk(chunk_id)
);
