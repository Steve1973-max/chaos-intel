from flask import Flask

app = Flask(__name__)

@app.route("/users")
def get_users():
    pass

@app.route("/items/<int:item_id>", methods=["GET", "DELETE"])
def item_ops(item_id):
    pass
