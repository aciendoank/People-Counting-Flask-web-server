# -*- encoding: utf-8 -*-

from apps import db, login_manager
from apps.authentication.util import hash_pass
from flask_login import UserMixin
from flask_dance.consumer.storage.sqla import OAuthConsumerMixin
from sqlalchemy import Column, Integer, String, LargeBinary, ForeignKey, Table
from sqlalchemy.orm import relationship


# This is the join table for the many-to-many relationship
roles_users = db.Table('roles_users',
    db.Column('user_id', db.Integer, db.ForeignKey('Users.id')),
    db.Column('role_id', db.Integer, db.ForeignKey('Role.id'))
)

class Role(db.Model):
    __tablename__ = 'Role'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(255))
    
    def __repr__(self):
        return f'<Role {self.name}>'

class Users(db.Model, UserMixin):
    __tablename__ = 'Users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True)
    email = db.Column(db.String(64), unique=True)
    password = db.Column(db.LargeBinary)

    # ADDED: This is the missing relationship
    roles = relationship('Role', secondary=roles_users,
        backref=db.backref('users', lazy='dynamic'))

    def __init__(self, **kwargs):
        # SECURE: Explicitly handle each field to prevent mass assignment
        self.username = kwargs.get('username')
        self.email = kwargs.get('email')
        
        # SECURE: Hash the password properly
        if kwargs.get('password'):
            self.password = hash_pass(kwargs.get('password'))
            
        self.oauth_github = kwargs.get('oauth_github', None)

    def __repr__(self):
        return str(self.username)


@login_manager.user_loader
def user_loader(id):
    return Users.query.filter_by(id=id).first()


@login_manager.request_loader
def request_loader(request):
    username = request.form.get('username')
    user = Users.query.filter_by(username=username).first()
    return user if user else None

class OAuth(OAuthConsumerMixin, db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey("Users.id", ondelete="cascade"), nullable=False)
    user = db.relationship(Users)