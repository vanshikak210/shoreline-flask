from __init__ import db
from datetime import datetime

class Survey(db.Model):
    __tablename__ = 'surveys'

    id = db.Column(db.Integer, primary_key=True)
    response = db.Column(db.String(32), nullable=False)
    name = db.Column(db.String(128), nullable=True)
    email = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    VALID_RESPONSES = ['donate', 'volunteer', 'none']

    def __init__(self, response, name=None, email=None):
        self.response = response
        self.name = name
        self.email = email

    def create(self):
        db.session.add(self)
        db.session.commit()
        return self

    def read(self):
        return {
            "id": self.id,
            "response": self.response,
            "name": self.name,
            "email": self.email,
            "created_at": self.created_at,
        }
