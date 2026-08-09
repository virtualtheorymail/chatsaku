from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity
)
from config import bcrypt
from models import db, UserLogin, User

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/register", methods=["POST"])
def register():

    data = request.get_json()

    nama = data.get("nama", "").strip()
    email = data.get("email", "").strip().lower()
    nomor = data.get("nomor_whatsapp", "").strip()
    password = data.get("password", "")

    if not nama:
        return jsonify({
            "success": False,
            "message": "Nama wajib diisi."
        }), 400

    if not email:
        return jsonify({
            "success": False,
            "message": "Email wajib diisi."
        }), 400

    if not nomor:
        return jsonify({
            "success": False,
            "message": "Nomor WhatsApp wajib diisi."
        }), 400

    if not password:
        return jsonify({
            "success": False,
            "message": "Password wajib diisi."
        }), 400

    if len(password) < 6:
        return jsonify({
            "success": False,
            "message": "Password minimal 6 karakter."
        }), 400

    if UserLogin.query.filter_by(email=email).first():
        return jsonify({
            "success": False,
            "message": "Email sudah digunakan."
        }), 400

    if UserLogin.query.filter_by(
        nomor_whatsapp=nomor
    ).first():

        return jsonify({
            "success": False,
            "message": "Nomor WhatsApp sudah digunakan."
        }), 400

    password_hash = bcrypt.generate_password_hash(
        password
    ).decode("utf-8")

    user = UserLogin(

        nama=nama,

        email=email,

        nomor_whatsapp=nomor,

        password=password_hash

    )

    db.session.add(user)
    db.session.commit()

    return jsonify({

        "success": True,

        "message": "Registrasi berhasil."

    }), 201

@auth_bp.route("/login", methods=["POST"])
def login():

    data = request.get_json() or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:

        return jsonify({
            "success": False,
            "message": "Email dan password wajib diisi."
        }), 400

    login_user = UserLogin.query.filter_by(
        email=email
    ).first()

    if login_user is None:

        return jsonify({
            "success": False,
            "message": "Email atau password salah."
        }), 401

    if not bcrypt.check_password_hash(
        login_user.password,
        password
    ):

        return jsonify({
            "success": False,
            "message": "Email atau password salah."
        }), 401

    # Pastikan user sudah memiliki nomor WhatsApp
    if not login_user.nomor_whatsapp:

        return jsonify({
            "success": False,
            "message": "Nomor WhatsApp belum dihubungkan."
        }), 400

    token = create_access_token(
        identity=str(login_user.id)
    )

    return jsonify({

        "success": True,

        "message": "Login berhasil",

        "token": token,

        "user": {

            "id": login_user.id,

            "nama": login_user.nama,

            "email": login_user.email,

            "nomor_whatsapp": login_user.nomor_whatsapp

        }

    }), 200

@auth_bp.route("/profile")
@jwt_required()
def profile():

    user_id = get_jwt_identity()

    user = UserLogin.query.get(user_id)

    if not user:

        return jsonify({

            "success": False

        }), 404

    return jsonify({

        "success": True,

        "user": {

            "id": user.id,

            "nama": user.nama,

            "email": user.email,

            "nomor_whatsapp": user.nomor_whatsapp

        }

    })

@auth_bp.route("/logout", methods=["POST"])
def logout():

    return jsonify({

        "success": True,

        "message": "Logout berhasil."

    })
