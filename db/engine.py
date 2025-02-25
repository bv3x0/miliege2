from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
import logging
import os
from .models import Base

class Database:
    """Database connection manager."""
    
    def __init__(self, db_url=None):
        """Initialize database connection."""
        if not db_url:
            # Default to SQLite database in the current directory
            db_url = os.getenv('DATABASE_URL', 'sqlite:///token_tracker.db')
        
        self.engine = create_engine(db_url, echo=False)
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)
        
        logging.info(f"Database initialized with {db_url}")
    
    def create_tables(self):
        """Create all tables defined in the models."""
        try:
            Base.metadata.create_all(self.engine)
            logging.info("Database tables created successfully")
        except Exception as e:
            logging.error(f"Error creating database tables: {e}")
            raise
    
    def get_session(self):
        """Get a new database session."""
        return self.Session()
    
    def close_sessions(self):
        """Close all sessions."""
        self.Session.remove()
        logging.info("Database sessions closed")
    
    def close(self):
        """Close the database connection."""
        self.close_sessions()
        if self.engine:
            self.engine.dispose()
            logging.info("Database engine disposed")
