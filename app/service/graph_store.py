from neo4j import GraphDatabase
from typing import Optional
  
class Neo4jDriver():     
    
    def __init__(self, uri: str, user: str, password: str, database: Optional[str] = "neo4j"):
        
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database
        self.entity_index = {}

    def _run(self, cypher: str, **params):
        
        with self.driver.session(database=self.database) as session:
            result = session.run(cypher, **params)
            return [dict(record) for record in result]