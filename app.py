import os
import uuid
import json
import xml.etree.ElementTree as ET
import networkx as nx
import matplotlib.pyplot as plt
from flask import Flask, request, render_template, redirect, url_for, send_file, flash

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['DIAGRAM_FOLDER'] = 'static'
app.secret_key = 'super-secret-key'  # Change in production

# ----------------------- Package Parsing -----------------------
def parse_ar_packages(package_elem, ns):
    package = {}
    package["short_name"] = package_elem.find("autosar:SHORT-NAME", ns).text if package_elem.find("autosar:SHORT-NAME", ns) is not None else "N/A"
    # Capture elements in this package
    elements = []
    elems = package_elem.find("autosar:ELEMENTS", ns)
    if elems is not None:
        for elem in elems:
            elem_info = {
                "tag": elem.tag.split('}')[1] if '}' in elem.tag else elem.tag,
                "short_name": elem.find("autosar:SHORT-NAME", ns).text if elem.find("autosar:SHORT-NAME", ns) is not None else "N/A",
                "uuid": elem.get("UUID", "N/A")
            }
            elements.append(elem_info)
    package["elements"] = elements
    # Recursively parse child packages
    child_packages = []
    ar_packages = package_elem.find("autosar:AR-PACKAGES", ns)
    if ar_packages is not None:
        for child in ar_packages.findall("autosar:AR-PACKAGE", ns):
            child_packages.append(parse_ar_packages(child, ns))
    package["packages"] = child_packages
    return package

# ----------------------- Graph Parsing -----------------------
def parse_arxml_to_composition_graph(xml_file_path):
    ns = {'autosar': 'http://autosar.org/schema/r4.0'}
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    G = nx.DiGraph()
    compositions = root.findall(".//autosar:COMPOSITION-SW-COMPONENT-TYPE", ns)
    for compo in compositions:
        compo_short_name_elem = compo.find("autosar:SHORT-NAME", ns)
        compo_name = compo_short_name_elem.text if compo_short_name_elem is not None else "UnnamedComposition"
        swc_prototypes = compo.findall(".//autosar:SW-COMPONENT-PROTOTYPE", ns)
        for scp in swc_prototypes:
            scp_short_name_elem = scp.find("autosar:SHORT-NAME", ns)
            if scp_short_name_elem is None:
                continue
            scp_short_name = scp_short_name_elem.text
            type_tref_elem = scp.find(".//autosar:TYPE-TREF", ns)
            if type_tref_elem is not None and type_tref_elem.text:
                type_path = type_tref_elem.text.strip()
                type_short_name = type_path.split("/")[-1]
            else:
                type_short_name = "UnknownType"
            node_label = f"{scp_short_name} ({type_short_name})"
            G.add_node(scp_short_name, label=node_label, composition=compo_name)
        connectors = compo.findall(".//autosar:ASSEMBLY-SW-CONNECTOR", ns)
        for conn in connectors:
            provider_elem = conn.find(".//autosar:PROVIDER-IREF", ns)
            requester_elem = conn.find(".//autosar:REQUESTER-IREF", ns)
            if provider_elem is None or requester_elem is None:
                continue
            prov_context_ref = provider_elem.find("autosar:CONTEXT-COMPONENT-REF", ns)
            req_context_ref = requester_elem.find("autosar:CONTEXT-COMPONENT-REF", ns)
            if prov_context_ref is not None and prov_context_ref.text:
                provider_proto_name = prov_context_ref.text.split("/")[-1]
            else:
                provider_proto_name = None
            if req_context_ref is not None and req_context_ref.text:
                requester_proto_name = req_context_ref.text.split("/")[-1]
            else:
                requester_proto_name = None
            if provider_proto_name and requester_proto_name:
                if provider_proto_name not in G.nodes:
                    G.add_node(provider_proto_name, label=provider_proto_name, composition=compo_name)
                if requester_proto_name not in G.nodes:
                    G.add_node(requester_proto_name, label=requester_proto_name, composition=compo_name)
                G.add_edge(provider_proto_name, requester_proto_name)
    return G

# ----------------------- Enhanced Dashboard Parsing -----------------------
def parse_arxml_for_dashboard(xml_file_path):
    ns = {'autosar': 'http://autosar.org/schema/r4.0'}
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    dashboard = {}

    # System Overview
    system_elem = root.find(".//autosar:SYSTEM", ns)
    if system_elem is not None:
        system_name_elem = system_elem.find("autosar:SHORT-NAME", ns)
        system_name = system_name_elem.text if system_name_elem is not None else "N/A"
        system_type_elem = system_elem.find("autosar:CATEGORY", ns)
        system_type = system_type_elem.text if system_type_elem is not None else "N/A"
    else:
        system_name = "N/A"
        system_type = "N/A"
    dashboard["system_overview"] = {
        "system_name": system_name,
        "system_type": system_type
    }

    # Package Structure (Hierarchical)
    packages = []
    root_packages = root.find("autosar:AR-PACKAGES", ns)
    if root_packages is not None:
        for pkg in root_packages.findall("autosar:AR-PACKAGE", ns):
            packages.append(parse_ar_packages(pkg, ns))
    dashboard["package_structure"] = packages

    # SWCs with Port Details – extract from APPLICATION-SW-COMPONENT-TYPE and SERVICE-SW-COMPONENT-TYPE
    swcs = []
    for comp in root.findall(".//autosar:APPLICATION-SW-COMPONENT-TYPE", ns) + root.findall(".//autosar:SERVICE-SW-COMPONENT-TYPE", ns):
        comp_name = comp.find("autosar:SHORT-NAME", ns).text if comp.find("autosar:SHORT-NAME", ns) is not None else "N/A"
        comp_uuid = comp.get("UUID", "N/A")
        ports = []
        ports_elem = comp.find("autosar:PORTS", ns)
        if ports_elem is not None:
            for port in ports_elem:
                port_short_name = port.find("autosar:SHORT-NAME", ns).text if port.find("autosar:SHORT-NAME", ns) is not None else "N/A"
                port_uuid = port.get("UUID", "N/A")
                iface_ref = None
                if port.find("autosar:PROVIDED-INTERFACE-TREF", ns) is not None:
                    iface_ref = port.find("autosar:PROVIDED-INTERFACE-TREF", ns).text
                elif port.find("autosar:REQUIRED-INTERFACE-TREF", ns) is not None:
                    iface_ref = port.find("autosar:REQUIRED-INTERFACE-TREF", ns).text
                ports.append({
                    "port_type": port.tag.split('}')[1] if '}' in port.tag else port.tag,
                    "short_name": port_short_name,
                    "uuid": port_uuid,
                    "interface_ref": iface_ref
                })
        swcs.append({"name": comp_name, "uuid": comp_uuid, "ports": ports})
    dashboard["swcs"] = swcs
    dashboard["swc_count"] = len(swcs)

    # Interfaces with DATA-ELEMENTS
    interfaces = []
    for iface in root.findall(".//autosar:SENDER-RECEIVER-INTERFACE", ns) + root.findall(".//autosar:CLIENT-SERVER-INTERFACE", ns):
        iface_name = iface.find("autosar:SHORT-NAME", ns).text if iface.find("autosar:SHORT-NAME", ns) is not None else "N/A"
        iface_uuid = iface.get("UUID", "N/A")
        iface_type = "Sender/Receiver" if iface.tag.endswith("SENDER-RECEIVER-INTERFACE") else "Client/Server"
        data_elements = []
        data_elems = iface.find("autosar:DATA-ELEMENTS", ns)
        if data_elems is not None:
            for var in data_elems.findall("autosar:VARIABLE-DATA-PROTOTYPE", ns):
                var_name = var.find("autosar:SHORT-NAME", ns).text if var.find("autosar:SHORT-NAME", ns) is not None else "N/A"
                var_uuid = var.get("UUID", "N/A")
                type_ref = var.find("autosar:TYPE-TREF", ns)
                type_ref_text = type_ref.text if type_ref is not None else "N/A"
                data_elements.append({"name": var_name, "uuid": var_uuid, "type_ref": type_ref_text})
        interfaces.append({
            "name": iface_name,
            "uuid": iface_uuid,
            "type": iface_type,
            "data_elements": data_elements
        })
    dashboard["interfaces"] = interfaces
    dashboard["interface_count"] = len(interfaces)

    # Signals (I-SIGNAL mappings are now added in Communication)
    signals = []
    for signal in root.findall(".//autosar:I-SIGNAL", ns):
        name_elem = signal.find("autosar:SHORT-NAME", ns)
        name = name_elem.text if name_elem is not None else "N/A"
        sys_sig_ref = signal.find("autosar:SYSTEM-SIGNAL-REF", ns)
        mapped_signal = sys_sig_ref.text if sys_sig_ref is not None else "N/A"
        signals.append({"name": name, "mapped_signal": mapped_signal})
    dashboard["signals"] = signals
    dashboard["signal_count"] = len(signals)

    # Connectors (ASSEMBLY and DELEGATION)
    connectors = []
    for conn in root.findall(".//autosar:ASSEMBLY-SW-CONNECTOR", ns):
        name_elem = conn.find("autosar:SHORT-NAME", ns)
        name = name_elem.text if name_elem is not None else "N/A"
        provider = "N/A"
        requester = "N/A"
        context_refs = conn.findall(".//autosar:CONTEXT-COMPONENT-REF", ns)
        if context_refs:
            provider = context_refs[0].text.split("/")[-1] if context_refs[0].text else "N/A"
        if len(context_refs) > 1:
            requester = context_refs[1].text.split("/")[-1] if context_refs[1].text else "N/A"
        connectors.append({"name": name, "provider": provider, "requester": requester})
    for conn in root.findall(".//autosar:DELEGATION-SW-CONNECTOR", ns):
        name_elem = conn.find("autosar:SHORT-NAME", ns)
        name = name_elem.text if name_elem is not None else "N/A"
        provider = "N/A"
        if conn.find(".//autosar:INNER-PORT-IREF", ns) is not None:
            inner = conn.find(".//autosar:INNER-PORT-IREF//autosar:TARGET-P-PORT-REF", ns)
            if inner is not None and inner.text:
                provider = inner.text.split("/")[-1]
        outer_port_elem = conn.find("autosar:OUTER-PORT-REF", ns)
        requester = outer_port_elem.text.split("/")[-1] if outer_port_elem is not None and outer_port_elem.text else "N/A"
        connectors.append({"name": name, "provider": provider, "requester": requester})
    dashboard["connectors"] = connectors
    dashboard["connector_count"] = len(connectors)

    # Functional Details – including events, runnables and variable accesses
    functional = []
    behaviors = root.findall(".//autosar:SWC-INTERNAL-BEHAVIOR", ns)
    for beh in behaviors:
        beh_name = beh.find("autosar:SHORT-NAME", ns).text if beh.find("autosar:SHORT-NAME", ns) is not None else "N/A"
        events_list = []
        events_elem = beh.find("autosar:EVENTS", ns)
        if events_elem is not None:
            for event in events_elem:
                event_type = event.tag.split('}')[1] if '}' in event.tag else event.tag
                event_name = event.find("autosar:SHORT-NAME", ns).text if event.find("autosar:SHORT-NAME", ns) is not None else "N/A"
                event_detail = {"type": event_type, "name": event_name}
                if event_type == "TIMING-EVENT":
                    period = event.find("autosar:PERIOD", ns)
                    if period is not None:
                        event_detail["period"] = period.text
                events_list.append(event_detail)
        runnables_list = []
        runnables_elem = beh.find("autosar:RUNNABLES", ns)
        if runnables_elem is not None:
            for runnable in runnables_elem.findall("autosar:RUNNABLE-ENTITY", ns):
                run_name = runnable.find("autosar:SHORT-NAME", ns).text if runnable.find("autosar:SHORT-NAME", ns) is not None else "N/A"
                min_interval = runnable.find("autosar:MINIMUM-START-INTERVAL", ns)
                min_interval_val = min_interval.text if min_interval is not None else "N/A"
                concurrently = runnable.find("autosar:CAN-BE-INVOKED-CONCURRENTLY", ns)
                concurrently_val = concurrently.text if concurrently is not None else "N/A"
                # Data Read Access
                data_read = []
                dr_access_elem = runnable.find("autosar:DATA-READ-ACCESSS", ns)
                if dr_access_elem is not None:
                    for va in dr_access_elem.findall("autosar:VARIABLE-ACCESS", ns):
                        va_name = va.find("autosar:SHORT-NAME", ns).text if va.find("autosar:SHORT-NAME", ns) is not None else "N/A"
                        av = va.find("autosar:ACCESSED-VARIABLE", ns)
                        details = {}
                        if av is not None:
                            port_ref = av.find("autosar:PORT-PROTOTYPE-REF", ns)
                            target_data_ref = av.find("autosar:TARGET-DATA-PROTOTYPE-REF", ns)
                            details["port_ref"] = port_ref.text if port_ref is not None else "N/A"
                            details["target_data_ref"] = target_data_ref.text if target_data_ref is not None else "N/A"
                        data_read.append({"short_name": va_name, "details": details})
                # Data Write Access
                data_write = []
                dw_access_elem = runnable.find("autosar:DATA-WRITE-ACCESSS", ns)
                if dw_access_elem is not None:
                    for va in dw_access_elem.findall("autosar:VARIABLE-ACCESS", ns):
                        va_name = va.find("autosar:SHORT-NAME", ns).text if va.find("autosar:SHORT-NAME", ns) is not None else "N/A"
                        av = va.find("autosar:ACCESSED-VARIABLE", ns)
                        details = {}
                        if av is not None:
                            port_ref = av.find("autosar:PORT-PROTOTYPE-REF", ns)
                            target_data_ref = av.find("autosar:TARGET-DATA-PROTOTYPE-REF", ns)
                            details["port_ref"] = port_ref.text if port_ref is not None else "N/A"
                            details["target_data_ref"] = target_data_ref.text if target_data_ref is not None else "N/A"
                        data_write.append({"short_name": va_name, "details": details})
                runnables_list.append({
                    "name": run_name,
                    "min_interval": min_interval_val,
                    "concurrent": concurrently_val,
                    "data_read_access": data_read,
                    "data_write_access": data_write
                })
        functional.append({
            "behavior": beh_name,
            "events": events_list,
            "runnables": runnables_list
        })
    dashboard["functional"] = functional

    # Diagnostic Details & Error Definitions
    diagnostic = []
    error_definitions = []
    for cs in root.findall(".//autosar:CLIENT-SERVER-INTERFACE", ns):
        iface_name = cs.find("autosar:SHORT-NAME", ns).text if cs.find("autosar:SHORT-NAME", ns) is not None else "N/A"
        possible_errors = cs.find("autosar:POSSIBLE-ERRORS", ns)
        if possible_errors is not None:
            errors = []
            for app_error in possible_errors.findall("autosar:APPLICATION-ERROR", ns):
                err_name = app_error.find("autosar:SHORT-NAME", ns).text if app_error.find("autosar:SHORT-NAME", ns) is not None else "N/A"
                err_code = app_error.find("autosar:ERROR-CODE", ns).text if app_error.find("autosar:ERROR-CODE", ns) is not None else "N/A"
                errors.append({"name": err_name, "code": err_code})
                error_definitions.append({
                    "interface": iface_name,
                    "error_name": err_name,
                    "error_code": err_code
                })
            diagnostic.append({
                "interface": iface_name,
                "errors": errors
            })
    dashboard["diagnostic"] = diagnostic
    dashboard["error_definitions"] = error_definitions

    # Resource Details from SWC-IMPLEMENTATION
    resource = []
    for impl in root.findall(".//autosar:SWC-IMPLEMENTATION", ns):
        comp_name = impl.find("autosar:SHORT-NAME", ns).text if impl.find("autosar:SHORT-NAME", ns) is not None else "N/A"
        resource_elem = impl.find("autosar:RESOURCE-CONSUMPTION", ns)
        resource_name = (resource_elem.find("autosar:SHORT-NAME", ns).text 
                         if resource_elem is not None and resource_elem.find("autosar:SHORT-NAME", ns) is not None 
                         else "N/A")
        resource.append({
            "component": comp_name,
            "resource_consumption": resource_name
        })
    dashboard["resource"] = resource

    # System Mappings (SWC-to-Implementation and Data Mappings)
    system_mappings = []
    for mapping in root.findall(".//autosar:SYSTEM-MAPPING", ns):
        mapping_short = mapping.find("autosar:SHORT-NAME", ns).text if mapping.find("autosar:SHORT-NAME", ns) is not None else "N/A"
        sw_impl_mappings = []
        sw_impl_mappings_elem = mapping.find("autosar:SW-IMPL-MAPPINGS", ns)
        if sw_impl_mappings_elem is not None:
            for swc_impl_mapping in sw_impl_mappings_elem.findall("autosar:SWC-TO-IMPL-MAPPING", ns):
                map_short = swc_impl_mapping.find("autosar:SHORT-NAME", ns).text if swc_impl_mapping.find("autosar:SHORT-NAME", ns) is not None else "N/A"
                comp_impl_ref = swc_impl_mapping.find("autosar:COMPONENT-IMPLEMENTATION-REF", ns).text if swc_impl_mapping.find("autosar:COMPONENT-IMPLEMENTATION-REF", ns) is not None else "N/A"
                comp_irefs = []
                comp_irefs_elem = swc_impl_mapping.find("autosar:COMPONENT-IREFS", ns)
                if comp_irefs_elem is not None:
                    for comp_iref in comp_irefs_elem.findall("autosar:COMPONENT-IREF", ns):
                        context = comp_iref.find("autosar:CONTEXT-COMPOSITION-REF", ns).text if comp_iref.find("autosar:CONTEXT-COMPOSITION-REF", ns) is not None else "N/A"
                        target = comp_iref.find("autosar:TARGET-COMPONENT-REF", ns).text if comp_iref.find("autosar:TARGET-COMPONENT-REF", ns) is not None else "N/A"
                        comp_irefs.append({"context": context, "target_component_ref": target})
                sw_impl_mappings.append({
                    "short_name": map_short,
                    "component_impl_ref": comp_impl_ref,
                    "component_irefs": comp_irefs
                })
        # Data Mappings for signals
        data_mappings = []
        data_mappings_elem = mapping.find("autosar:DATA-MAPPINGS", ns)
        if data_mappings_elem is not None:
            for mapping_elem in data_mappings_elem.findall("autosar:SENDER-RECEIVER-TO-SIGNAL-MAPPING", ns):
                data_element_iref = mapping_elem.find("autosar:DATA-ELEMENT-IREF", ns)
                context_comp = data_element_iref.find("autosar:CONTEXT-COMPOSITION-REF", ns).text if data_element_iref is not None and data_element_iref.find("autosar:CONTEXT-COMPOSITION-REF", ns) is not None else "N/A"
                target_data_ref = data_element_iref.find("autosar:TARGET-DATA-PROTOTYPE-REF", ns).text if data_element_iref is not None and data_element_iref.find("autosar:TARGET-DATA-PROTOTYPE-REF", ns) is not None else "N/A"
                system_signal_ref = mapping_elem.find("autosar:SYSTEM-SIGNAL-REF", ns).text if mapping_elem.find("autosar:SYSTEM-SIGNAL-REF", ns) is not None else "N/A"
                data_mappings.append({
                    "context_composition": context_comp,
                    "target_data_prototype_ref": target_data_ref,
                    "system_signal_ref": system_signal_ref
                })
        mapping_obj = {"short_name": mapping_short, "sw_impl_mappings": sw_impl_mappings}
        if data_mappings:
            mapping_obj["data_mappings"] = data_mappings
        system_mappings.append(mapping_obj)
    dashboard["system_mappings"] = system_mappings

    # Communication Details – I-SIGNAL and I-SIGNAL-I-PDU mappings
    i_signals = []
    for i_sig in root.findall(".//autosar:I-SIGNAL", ns):
        i_sig_name = i_sig.find("autosar:SHORT-NAME", ns).text if i_sig.find("autosar:SHORT-NAME", ns) is not None else "N/A"
        i_sig_uuid = i_sig.get("UUID", "N/A")
        sys_sig_ref = i_sig.find("autosar:SYSTEM-SIGNAL-REF", ns)
        sys_sig = sys_sig_ref.text if sys_sig_ref is not None else "N/A"
        i_signals.append({"name": i_sig_name, "uuid": i_sig_uuid, "system_signal_ref": sys_sig})
    i_signal_ipdus = []
    for ipdu in root.findall(".//autosar:I-SIGNAL-I-PDU", ns):
        ipdu_name = ipdu.find("autosar:SHORT-NAME", ns).text if ipdu.find("autosar:SHORT-NAME", ns) is not None else "N/A"
        ipdu_uuid = ipdu.get("UUID", "N/A")
        mappings = []
        mappings_elem = ipdu.find("autosar:I-SIGNAL-TO-PDU-MAPPINGS", ns)
        if mappings_elem is not None:
            for mapping in mappings_elem.findall("autosar:I-SIGNAL-TO-I-PDU-MAPPING", ns):
                map_short = mapping.find("autosar:SHORT-NAME", ns).text if mapping.find("autosar:SHORT-NAME", ns) is not None else "N/A"
                i_sig_ref = mapping.find("autosar:I-SIGNAL-REF", ns).text if mapping.find("autosar:I-SIGNAL-REF", ns) is not None else "N/A"
                mappings.append({"short_name": map_short, "i_signal_ref": i_sig_ref})
        i_signal_ipdus.append({"name": ipdu_name, "uuid": ipdu_uuid, "mappings": mappings})
    dashboard["communication"] = {"i_signals": i_signals, "i_signal_ipdus": i_signal_ipdus}

    return dashboard

# ----------------------- Flask Routes -----------------------
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
            # Save the uploaded ARXML file temporarily.
            filename = str(uuid.uuid4()) + ".arxml"
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            file.save(file_path)

            try:
                # Generate composition diagram (Architecture View)
                G = parse_arxml_to_composition_graph(file_path)
                pos = nx.spring_layout(G, k=0.5, seed=42)
                plt.figure(figsize=(10, 8))
                labels = nx.get_node_attributes(G, "label")
                nx.draw(G, pos, with_labels=True, labels=labels, node_size=2500,
                        node_color="lightgreen", font_size=10, arrows=True,
                        arrowstyle="-|>", arrowsize=12)
                diagram_filename = str(uuid.uuid4()) + ".png"
                diagram_path = os.path.join(app.config["DIAGRAM_FOLDER"], diagram_filename)
                os.makedirs(app.config["DIAGRAM_FOLDER"], exist_ok=True)
                plt.savefig(diagram_path, dpi=150, bbox_inches='tight')
                plt.close()

                # Parse ARXML to extract dashboard data.
                dashboard_data = parse_arxml_for_dashboard(file_path)

                # Write the dashboard data as JSON in outputs/ with the same base name as the ARXML file.
                os.makedirs("outputs", exist_ok=True)
                json_filename = os.path.splitext(filename)[0] + ".json"
                json_path = os.path.join("outputs", json_filename)
                with open(json_path, "w") as json_file:
                    json.dump(dashboard_data, json_file, indent=2)

                # Remove the temporary ARXML file.
                os.remove(file_path)
                return render_template("dashboard.html", diagram=diagram_filename, dashboard=dashboard_data)
            except Exception as e:
                flash(f"Error processing file: {e}")
                return redirect(request.url)
    return render_template("dashboard.html", diagram=None, dashboard=None)

@app.route("/diagram/<filename>")
def diagram(filename):
    return send_file(os.path.join(app.config["DIAGRAM_FOLDER"], filename), mimetype="image/png")

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
