import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USER = os.getenv("NEO4J_USER", "")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USER, NEO4J_PASSWORD)
)


def save_node(tx, label, name):
    query = f"""
    MERGE (n:`{label}` {{name: $name}})
    SET n.id = $name
    """
    tx.run(query, name=name)


def save_relation(tx, source, relation, target):
    query = f"""
    MERGE (a {{name: $source}})
    MERGE (b {{name: $target}})
    MERGE (a)-[r:`{relation}`]->(b)
    """
    tx.run(query, source=source, target=target)


def save_to_neo4j(result):
    with driver.session(database=NEO4J_DATABASE) as session:

        for player in result.get("players", []):
            session.execute_write(save_node, "Player", player)

        for team in result.get("teams", []):
            session.execute_write(save_node, "Team", team)

        for champion in result.get("champions", []):
            session.execute_write(save_node, "Champion", champion)

        for objective in result.get("objectives", []):
            session.execute_write(save_node, "Objective", objective)

        for tournament in result.get("tournaments", []):
            session.execute_write(save_node, "Tournament", tournament)

        for rel in result.get("relations", []):
            source = rel.get("source")
            relation = rel.get("relation")
            target = rel.get("target")

            if source and relation and target:
                session.execute_write(save_relation, source, relation, target)

    print("✅ Neo4j 저장 완료")