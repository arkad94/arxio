import os
import uuid
import json
from flask import Flask, request, render_template, redirect, url_for, send_file, flash, Response
from parser import parse_arxml_for_dashboard
from diagram2d import generate_2d_diagram
from diagram3d import generate_3d_diagram_html

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['DIAGRAM_FOLDER'] = 'static'
app.secret_key = 'super-secret-key'  # Change this for production

@app.route("/", methods=["GET", "POST"])
def dashboard_view():
    if request.method == "POST":
        if "arxml_file" not in request.files:
            flash("No file part in request.")
            return redirect(request.url)
        file = request.files["arxml_file"]
        if file.filename == "":
            flash("No file selected.")
            return redirect(request.url)
        if file:
            filename = str(uuid.uuid4()) + ".arxml"
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            file.save(file_path)
            try:
                # Generate the 2D diagram using the diagram2d module.
                diagram_filename = generate_2d_diagram(file_path, app.config["DIAGRAM_FOLDER"])
                # Parse ARXML for dashboard data.
                dashboard_data = parse_arxml_for_dashboard(file_path)
                os.makedirs("outputs", exist_ok=True)
                json_filename = os.path.splitext(filename)[0] + ".json"
                json_path = os.path.join("outputs", json_filename)
                with open(json_path, "w", encoding="utf-8") as json_file:
                    json.dump(dashboard_data, json_file, indent=2)
                return render_template("dashboard.html", diagram=diagram_filename, dashboard=dashboard_data, arxml_filename=filename)
            except Exception as e:
                flash(f"Error processing file: {e}")
                return redirect(request.url)
    return render_template("dashboard.html", diagram=None, dashboard=None, arxml_filename=None)

@app.route("/diagram/<filename>")
def diagram(filename):
    return send_file(os.path.join(app.config["DIAGRAM_FOLDER"], filename), mimetype="image/png")

@app.route("/diagram3d/<filename>")
def diagram3d(filename):
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    html_str = generate_3d_diagram_html(file_path)
    return Response(html_str, mimetype="text/html")

# Dummy drill-down routes for detailed views.
@app.route("/swc/<uuid>")
def swc_detail(uuid):
    return f"Detailed view for SWC {uuid} (Under construction)"

@app.route("/interface/<uuid>")
def interface_detail(uuid):
    return f"Detailed view for Interface {uuid} (Under construction)"

@app.route("/signal/<name>")
def signal_detail(name):
    return f"Detailed view for Signal {name} (Under construction)"

@app.route("/connector/<name>")
def connector_detail(name):
    return f"Detailed view for Connector {name} (Under construction)"

@app.route("/functional/<behavior>")
def functional_detail(behavior):
    return f"Detailed functional view for behavior {behavior} (Under construction)"

@app.route("/diagnostic/<interface>")
def diagnostic_detail(interface):
    return f"Detailed diagnostic view for interface {interface} (Under construction)"

@app.route("/resource/<component>")
def resource_detail(component):
    return f"Detailed resource view for component {component} (Under construction)"

@app.route("/error/<interface>")
def error_detail(interface):
    return f"Detailed error view for interface {interface} (Under construction)"

if __name__ == "__main__":
    app.run(debug=True)
