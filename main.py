from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room, send
import random
from string import ascii_uppercase, ascii_letters, digits
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

DB_NAME = "rumorchatDB"
DB_USER = "postgres"
DB_PASSWORD = "rumorchat"

app = Flask(__name__)
app.config["SECRET_KEY"] = "abc"

app.config["SQLALCHEMY_DATABASE_URI"] = f"postgresql://{DB_USER}:{DB_PASSWORD}@localhost/{DB_NAME}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# TODO: Add a "Leave Room" button? 
# TODO: Fully Incorporate database into the chat app
# TODO: Incorporate a separate, private client-side chat box that logs messages to the database
# TODO: Incoporate uncensored large-language model for the user to chat to in that separate chat box, for rumor-geneartion/detection purposes.



# initialisation object for database
db = SQLAlchemy(app)

# Database Schema
class Rooms(db.Model):
    code = db.Column(db.String, primary_key=True)
    members = db.Column(db.String) # Storing members as a comma-separated string

    # Relationship
    messages = db.relationship('Messages', backref='room_info', lazy=True)

class Messages(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    current_room_code = db.Column(db.String, db.ForeignKey('rooms.code'), nullable=True)
    original_room_code = db.Column(db.String, nullable=False)
    name = db.Column(db.String, nullable=False)
    message = db.Column(db.String, nullable=False)
    date = db.Column(db.DateTime, nullable=False)

# initialisation object for socketio library
socketio = SocketIO(app)

# TODO: This is currently stored in RAM. Need to store in database (PostgresSQL).
# rooms = {}

def generate_unique_code(length):
    while True:
        code = ""
        for _ in range(length):
            code += random.choice(ascii_uppercase + digits)
        # return code if indeed unique   
        room_info = Rooms.query.filter_by(code=code).first()
        if room_info is None:
            return code

# Routes

# Home Page
@app.route("/", methods=["GET", "POST"])
def home():
    # Clear session when user goes to home page
    # so that they can't navigate directly to chat page without entering name and room code
    session.clear()
    if request.method == "POST":
        # attempt to grab values from form; returns None if doesn't exist
        name = request.form.get("name")
        code = request.form.get("code")
        # False if doesn't exist
        join = request.form.get("join", False)
        create = request.form.get("create", False)
        
        # Check if name contains symbols that are not typically safe
        if not name or not all(char in ascii_letters + digits + " " for char in name):
            # code=code and name=name to preserve values in form on render_template-initiated reload.
            return render_template("home.html", error="Please enter a valid name (letters, numbers and space only)", code=code, name=name)
        
        if join != False and not code:
            return render_template("home.html", error="Please enter a room code", code=code, name=name)
    
        # room = code
        room_info = Rooms.query.filter_by(code=code).first()
        if room_info:
            members_list = room_info.members.split(",") if room_info.members else []
        if create != False:
            code  = generate_unique_code(6)
            # rooms[room] = {"members":[], "messages":[]}
            new_room = Rooms(code=code , members="")
            db.session.add(new_room)
            db.session.commit()
            
        # if not create, we assume they are trying to join a room
        
        
        # Refuse to join if room doesn't exist or name already exists in room
        elif room_info is None:
            return render_template("home.html", error="Room code does not exist", code=code, name=name)
        elif name in members_list:
            # If the name already exists in the room's members
            return render_template("home.html", error="Name already exists in the room", code=code, name=name)

        # Session is a semi-permanent way to store information about user
        # Temporary secure data stored in the server; expires after awhile
        # Stored persistently between requests
        session["room"] = code
        session["name"] = name
        return redirect(url_for("room"))
    
    return render_template("home.html")

@app.route("/room")
def room():
    room = session.get("room")
    # Ensure user can only go to /room route if they either generated a new room
    # or joined an existing room from the home page
    room_info = Rooms.query.filter_by(code=room).first()
    if room is None or session.get("name") is None or room_info is None:
        return redirect(url_for("home"))
    # Extracting messages
    messages_list = [
        {
            "name": message.name,
            "message": message.message,
            "date": message.date.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for message in room_info.messages
    ]
    return render_template("room.html",code=room, messages=messages_list)

@socketio.on("message")
def message(data):
    room = session.get("room")
    room_info = Rooms.query.filter_by(code=room).first()
    if room_info is None:
        return
    
    content = {
        "name":session.get("name"),
        "message":data["data"],
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    # On receiving data from a client, send it to all clients in the room
    send(content, to=room)
    # Save message to room's messages history
    # rooms[room]["messages"].append(content)
    msg = Messages(current_room_code=room, original_room_code=room, name=content["name"], message=content["message"], date=content["date"])
    db.session.add(msg)
    db.session.commit()
    print(f"{session.get('name')} said: {data['data']} in room {room}")

# using the initialisation object for socketio
@socketio.on("connect")
def connect(auth):
    room = session.get("room")
    name = session.get("name")
    
    if not room or not name:
        return
    
    room_info = Rooms.query.filter_by(code=room).first()
    if room_info is None:
        # Leave room as it shouldn't exist
        leave_room(room)
        return

    join_room(room)
    content = {
        "name":name,
        "message":f"{name} has joined the room",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    send(content, to=room)
    
    # Save message to room's messages history
    # rooms[room]["messages"].append(content)
    msg = Messages(current_room_code=room, original_room_code=room, name=content["name"], message=content["message"], date=content["date"])
    db.session.add(msg)
    db.session.commit()
    
    members_list = room_info.members.split(",") if room_info.members else []
    # Add if name doesn't exist; prevents duplicate names in room upon refresh from same session
    if name not in members_list:
        members_list.append(name)
    room_info.members = ",".join(members_list)
    db.session.commit()
    emit("memberChange", members_list, to=room)
    print(f"{name} has joined room {room}. Current Members: {members_list}")
    

@socketio.on("disconnect")
def disconnect():
    room = session.get("room")
    name = session.get("name")
    leave_room(room)
    print(f"{name} has left room {room}") 
    room_info = Rooms.query.filter_by(code=room).first()
    
    content = {
        "name":name,
        "message":f"{name} has left the room",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Save message to room's messages history
    msg = Messages(current_room_code=room, original_room_code=room, name=content["name"], message=content["message"], date=content["date"])
    db.session.add(msg)
    db.session.commit()
    
    
    members_list = []
    if room_info:
        members_list = room_info.members.split(",") if room_info.members else []
        if name in members_list:
            members_list.remove(name)
        room_info.members = ",".join(members_list)
        db.session.commit()
        if not members_list:
            db.session.delete(room_info)
            db.session.commit()
            return
            
    send(content, to=room)
    emit("memberChange", members_list, to=room) 
     

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True)