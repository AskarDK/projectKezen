from main import db

class Interest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class RelatedInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    interest_id = db.Column(db.Integer, db.ForeignKey('interest.id'), nullable=False)
    related_id = db.Column(db.Integer, db.ForeignKey('interest.id'), nullable=False)
