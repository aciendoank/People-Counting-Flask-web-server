# -*- encoding: utf-8 -*-

from flask import flash,render_template, redirect, request, url_for
from flask_login import (
    current_user,
    login_user,
    logout_user
)

from flask_dance.contrib.github import github

from apps import db, login_manager
from apps.authentication import blueprint
from apps.authentication.forms import LoginForm, CreateAccountForm
from apps.authentication.models import Users

from apps.authentication.util import verify_pass


@blueprint.route('/')
def route_default():
    return redirect(url_for('authentication_blueprint.login'))

# Login & Registration

@blueprint.route("/github")
def login_github():
    """ Github login """
    if not github.authorized:
        return redirect(url_for("github.login"))

    res = github.get("/user")
    return redirect(url_for('home_blueprint.dashboard'))
    
@blueprint.route('/login', methods=['GET', 'POST'])
def login():
    login_form = LoginForm(request.form)
    
    if request.method == 'POST':
        # read form data
        username = request.form.get('username')
        password = request.form.get('password')

        # Locate user
        user = Users.query.filter_by(username=username).first()

        # Check the password
        if user and verify_pass(password, user.password):
            login_user(user)
            # Arahkan ke dashboard setelah login berhasil
            return redirect(url_for('home_blueprint.dashboard'))

        # Jika username atau password salah
        flash('Pengguna atau kata sandi salah.', 'danger')
        return redirect(url_for('authentication_blueprint.login'))

    # Tampilkan formulir login pada permintaan GET
    return render_template('accounts/login.html', form=login_form)


@blueprint.route('/register', methods=['GET', 'POST'])
def register():
    # Only process form data on POST request
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        # Check if any field is empty
        if not all([username, email, password]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('authentication_blueprint.register'))

        # Check if username already exists
        user = Users.query.filter_by(username=username).first()
        if user:
            flash('Username already registered. Please choose a different one.', 'danger')
            return redirect(url_for('authentication_blueprint.register'))

        # Check if email already exists
        user = Users.query.filter_by(email=email).first()
        if user:
            flash('Email already registered. Please use a different email address.', 'danger')
            return redirect(url_for('authentication_blueprint.register'))

        # Hash the password securely
        hashed_password = hash_pass(password)

        # Create the new user with explicit fields
        new_user = Users(
            username=username,
            email=email,
            password=hashed_password
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully! You can now log in.', 'success')
            return redirect(url_for('authentication_blueprint.login'))

        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {str(e)}', 'danger')
            return redirect(url_for('authentication_blueprint.register'))

    # Render the form for GET requests
    return render_template('accounts/register.html')


@blueprint.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('authentication_blueprint.login'))


# Errors

@login_manager.unauthorized_handler
def unauthorized_handler():
    return render_template('home/page-403.html'), 403


@blueprint.errorhandler(403)
def access_forbidden(error):
    return render_template('home/page-403.html'), 403


@blueprint.errorhandler(404)
def not_found_error(error):
    return render_template('home/page-404.html'), 404


@blueprint.errorhandler(500)
def internal_error(error):
    return render_template('home/page-500.html'), 500
