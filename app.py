import os
import uuid
import json
import xml.etree.ElementTree as ET
import networkx as nx
import matplotlib
# Set the backend to a non-GUI one (Agg) to avoid threading issues.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Flask, request, render_template, redirect, url_for, send_file, flash, Response
import plotly.graph_objects as go

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['DIAGRAM_FOLDER'] = 'static'
app.secret_key = 'super-secret-key'  # Change in production

# ----------------------- Generic Recursive XML Parser -----------------------
def parse_xml_element(elem):
    """
    Recursively parse an XML element into a dictionary representation.
    This function is agnostic to the schema and returns every element,
    its attributes, text content, and children.
    """
    result = {}
    if '}' in elem.tag:
        result['tag'] = elem.tag.split('}', 1)[1]
    else:
        result['tag'] = elem.tag

    if elem.attrib:
        result['attributes'] = elem.attrib

    text = elem.text.strip() if elem.text else ""
    if text:
        result['text'] = text

    children = list(elem)
    if children:
        result['children'] = [parse_xml_element(child) for child in children]
    return result

def parse_arxml_generic(xml_file_path):
    """
    Parse an ARXML file into a complete generic dictionary representation.
    This is useful to see the entire structure and debug unexpected elements.
    """
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    return parse_xml_element(root)

# ----------------------- Helper Functions for Robust Parsing -----------------------
def safe_find(elem, path, ns):
    found = elem.find(path, ns)
    return found.text.strip() if found is not None and found.text else "N/A"

def extract_short_name(elem, ns):
    sn = elem.find("autosar:SHORT-NAME", ns)
    return sn.text.strip() if sn is not None and sn.text else "N/A"

# ----------------------- Specialized AUTOSAR Parsers -----------------------
def parse_ar_packages(package_elem, ns):
    """
    Recursively parse AR-PACKAGE elements from an AUTOSAR ARXML file.
    """
    package = {}
    package["short_name"] = extract_short_name(package_elem, ns)
    package["attributes"] = package_elem.attrib
    elements = []
    elems = package_elem.find("autosar:ELEMENTS", ns)
    if elems is not None:
        for elem in elems:
            elem_info = {
                "tag": elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag,
                "short_name": extract_short_name(elem, ns),
                "uuid": elem.get("UUID", "N/A"),
                "attributes": elem.attrib
            }
            cat = elem.find("autosar:CATEGORY", ns)
            if cat is not None and cat.text:
                elem_info["category"] = cat.text.strip()
            desc = elem.find("autosar:DESC", ns)
            if desc is not None:
                l2 = desc.find("autosar:L-2", ns)
                if l2 is not None and l2.text:
                    elem_info["description"] = l2.text.strip()
            elements.append(elem_info)
    package["elements"] = elements
    child_packages = []
    ar_packages = package_elem.find("autosar:AR-PACKAGES", ns)
    if ar_packages is not None:
        for child in ar_packages.findall("autosar:AR-PACKAGE", ns):
            child_packages.append(parse_ar_packages(child, ns))
    package["packages"] = child_packages
    return package

def parse_arxml_to_broader_composition_graph(xml_file_path):
    """
    Build a universal composition graph from an ARXML file.
    
    This function:
      1. Uses COMPOSITION and ASSEMBLY/DELEGATION connectors if available.
      2. Falls back to matching Provided/Required interface names.
      3. Adds internal constituents (Ports, Runnables, Events) as sub-nodes.
      4. Deduplicates duplicate edges.
    """
    ns = {'autosar': 'http://autosar.org/schema/r4.0'}
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    G = nx.DiGraph()

    # Helper to add a node with type (for color-coding)
    def add_node_with_type(node_name, node_label, node_type):
        if node_name not in G.nodes:
            G.add_node(node_name, label=node_label, type=node_type)

    ######################################
    # 1) Parse Compositions & Connectors
    ######################################
    compositions = root.findall(".//autosar:COMPOSITION-SW-COMPONENT-TYPE", ns)
    for compo in compositions:
        compo_name = safe_find(compo, "autosar:SHORT-NAME", ns)
        add_node_with_type(compo_name, compo_name, "Composition")
        swc_prototypes = compo.findall(".//autosar:SW-COMPONENT-PROTOTYPE", ns)
        for swc in swc_prototypes:
            swc_name = safe_find(swc, "autosar:SHORT-NAME", ns)
            type_tref_elem = swc.find(".//autosar:TYPE-TREF", ns)
            if type_tref_elem is not None and type_tref_elem.text:
                type_short_name = type_tref_elem.text.strip().split("/")[-1]
            else:
                type_short_name = "UnknownType"
            if "Service" in type_short_name or "IoHwAb" in type_short_name:
                node_type = "Service"
            elif "Composition" in type_short_name:
                node_type = "Composition"
            else:
                node_type = "SWC"
            add_node_with_type(swc_name, f"{swc_name} ({type_short_name})", node_type)
            G.add_edge(compo_name, swc_name, relation="Component")
        # Assembly connectors
        connectors = compo.findall(".//autosar:ASSEMBLY-SW-CONNECTOR", ns)
        for conn in connectors:
            provider_elem = conn.find(".//autosar:PROVIDER-IREF", ns)
            requester_elem = conn.find(".//autosar:REQUESTER-IREF", ns)
            if provider_elem is None or requester_elem is None:
                continue
            prov_context = provider_elem.find("autosar:CONTEXT-COMPONENT-REF", ns)
            req_context = requester_elem.find("autosar:CONTEXT-COMPONENT-REF", ns)
            provider_proto = (prov_context.text.strip().split("/")[-1]
                              if prov_context is not None and prov_context.text
                              else "Unknown")
            requester_proto = (req_context.text.strip().split("/")[-1]
                               if req_context is not None and req_context.text
                               else "Unknown")
            add_node_with_type(provider_proto, provider_proto, "SWC")
            add_node_with_type(requester_proto, requester_proto, "SWC")
            if not G.has_edge(provider_proto, requester_proto):
                G.add_edge(provider_proto, requester_proto, relation="AssemblyConnector")
        # Delegation connectors
        delegation_connectors = compo.findall(".//autosar:DELEGATION-SW-CONNECTOR", ns)
        for dconn in delegation_connectors:
            inner = dconn.find(".//autosar:INNER-PORT-IREF", ns)
            outer = dconn.find("autosar:OUTER-PORT-REF", ns)
            if inner is not None and outer is not None and outer.text:
                inner_comp = inner.find(".//autosar:CONTEXT-COMPONENT-REF", ns)
                inner_comp_name = (inner_comp.text.strip().split("/")[-1]
                                   if inner_comp is not None and inner_comp.text
                                   else "UnknownInner")
                outer_port_name = outer.text.strip().split("/")[-1]
                add_node_with_type(inner_comp_name, inner_comp_name, "SWC")
                add_node_with_type(outer_port_name, outer_port_name, "SWC")
                if not G.has_edge(inner_comp_name, outer_port_name):
                    G.add_edge(inner_comp_name, outer_port_name, relation="DelegationConnector")

    ############################################################
    # 2) Parse SWCs, their Ports, Runnables, and Events (fallback)
    ############################################################
    swc_types = (root.findall(".//autosar:APPLICATION-SW-COMPONENT-TYPE", ns) +
                 root.findall(".//autosar:SERVICE-SW-COMPONENT-TYPE", ns))
    provided_interfaces = {}
    required_interfaces = {}
    for swc in swc_types:
        swc_name = safe_find(swc, "autosar:SHORT-NAME", ns)
        if swc.tag.endswith("SERVICE-SW-COMPONENT-TYPE"):
            node_type = "Service"
        else:
            node_type = "SWC"
        add_node_with_type(swc_name, swc_name, node_type)
        # Process ports
        ports_elem = swc.find("autosar:PORTS", ns)
        if ports_elem is not None:
            for port in ports_elem:
                port_short_name = safe_find(port, "autosar:SHORT-NAME", ns)
                port_node = f"{swc_name}:{port_short_name}"
                add_node_with_type(port_node, port_short_name, "Port")
                G.add_edge(swc_name, port_node, relation="hasPort")
                provided = port.find("autosar:PROVIDED-INTERFACE-TREF", ns)
                required = port.find("autosar:REQUIRED-INTERFACE-TREF", ns)
                if provided is not None and provided.text:
                    iface_name = provided.text.strip().split("/")[-1]
                    provided_interfaces.setdefault(iface_name, set()).add(swc_name)
                    G.add_edge(port_node, iface_name, relation="providesInterface")
                elif required is not None and required.text:
                    iface_name = required.text.strip().split("/")[-1]
                    required_interfaces.setdefault(iface_name, set()).add(swc_name)
                    G.add_edge(port_node, iface_name, relation="requiresInterface")
        # Process internal behaviors: runnables and events
        swc_internals = swc.find(".//autosar:INTERNAL-BEHAVIORS", ns)
        if swc_internals is not None:
            for ib in swc_internals.findall("autosar:SWC-INTERNAL-BEHAVIOR", ns):
                # Runnables
                runnables_elem = ib.find("autosar:RUNNABLES", ns)
                if runnables_elem is not None:
                    for runnable in runnables_elem.findall("autosar:RUNNABLE-ENTITY", ns):
                        r_name = safe_find(runnable, "autosar:SHORT-NAME", ns)
                        run_node = f"{swc_name}::{r_name}"
                        add_node_with_type(run_node, r_name, "Runnable")
                        G.add_edge(swc_name, run_node, relation="runnable")
                # Events
                events_elem = ib.find("autosar:EVENTS", ns)
                if events_elem is not None:
                    for ev in events_elem:
                        ev_type = ev.tag.split('}')[-1]
                        ev_name = safe_find(ev, "autosar:SHORT-NAME", ns)
                        ev_node = f"{swc_name}::event::{ev_name}"
                        add_node_with_type(ev_node, ev_name, "Event")
                        G.add_edge(swc_name, ev_node, relation="event")
                        start_ref = ev.find("autosar:START-ON-EVENT-REF", ns)
                        if start_ref is not None and start_ref.text:
                            run_name = start_ref.text.strip().split("/")[-1]
                            run_node = f"{swc_name}::{run_name}"
                            if run_node in G.nodes:
                                G.add_edge(ev_node, run_node, relation="startsRunnable")
    ############################################################
    # 3) Build edges from matched Provided/Required interfaces
    ############################################################
    for iface_name, providers in provided_interfaces.items():
        if iface_name in required_interfaces:
            for p in providers:
                for r in required_interfaces[iface_name]:
                    if p != r and not G.has_edge(p, r):
                        G.add_edge(p, r, relation="Provides/Requires")
    ############################################################
    # 4) Add Interface nodes (if not already added)
    ############################################################
    sr_ifaces = root.findall(".//autosar:SENDER-RECEIVER-INTERFACE", ns)
    for iface in sr_ifaces:
        iface_name = safe_find(iface, "autosar:SHORT-NAME", ns)
        add_node_with_type(iface_name, iface_name, "Interface")
    cs_ifaces = root.findall(".//autosar:CLIENT-SERVER-INTERFACE", ns)
    for iface in cs_ifaces:
        iface_name = safe_find(iface, "autosar:SHORT-NAME", ns)
        add_node_with_type(iface_name, iface_name, "Interface")

    return G

def parse_arxml_for_dashboard(xml_file_path):
    """
    Parse ARXML for dashboard data.
    Extracts known AUTOSAR elements using safe accessors while remaining robust
    to different and more complex ARXML file structures.
    """
    ns = {'autosar': 'http://autosar.org/schema/r4.0'}
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    dashboard = {}

    # System Overview
    system_elem = root.find(".//autosar:SYSTEM", ns)
    if system_elem is not None:
        system_name = safe_find(system_elem, "autosar:SHORT-NAME", ns)
        system_type = safe_find(system_elem, "autosar:CATEGORY", ns)
    else:
        system_name = "N/A"
        system_type = "N/A"
    dashboard["system_overview"] = {
        "system_name": system_name,
        "system_type": system_type,
        "attributes": system_elem.attrib if system_elem is not None else {}
    }

    # Package Structure
    packages = []
    root_packages = root.find("autosar:AR-PACKAGES", ns)
    if root_packages is not None:
        for pkg in root_packages.findall("autosar:AR-PACKAGE", ns):
            packages.append(parse_ar_packages(pkg, ns))
    dashboard["package_structure"] = packages

    # SWCs (Components)
    swcs = []
    swc_types = root.findall(".//autosar:APPLICATION-SW-COMPONENT-TYPE", ns) + root.findall(".//autosar:SERVICE-SW-COMPONENT-TYPE", ns)
    for comp in swc_types:
        comp_name = safe_find(comp, "autosar:SHORT-NAME", ns)
        comp_uuid = comp.get("UUID", "N/A")
        ports = []
        ports_elem = comp.find("autosar:PORTS", ns)
        if ports_elem is not None:
            for port in ports_elem:
                port_tag = port.tag.split('}')[-1] if '}' in port.tag else port.tag
                port_short_name = safe_find(port, "autosar:SHORT-NAME", ns)
                port_uuid = port.get("UUID", "N/A")
                interface_ref = None
                iface_dest = None
                if port.find("autosar:PROVIDED-INTERFACE-TREF", ns) is not None:
                    prov = port.find("autosar:PROVIDED-INTERFACE-TREF", ns)
                    interface_ref = prov.text.strip() if prov.text else "N/A"
                    iface_dest = prov.get("DEST", "N/A")
                elif port.find("autosar:REQUIRED-INTERFACE-TREF", ns) is not None:
                    req = port.find("autosar:REQUIRED-INTERFACE-TREF", ns)
                    interface_ref = req.text.strip() if req.text else "N/A"
                    iface_dest = req.get("DEST", "N/A")
                ports.append({
                    "port_type": port_tag,
                    "short_name": port_short_name,
                    "uuid": port_uuid,
                    "interface_ref": interface_ref,
                    "interface_ref_dest": iface_dest,
                    "attributes": port.attrib
                })
        swcs.append({"name": comp_name, "uuid": comp_uuid, "ports": ports, "attributes": comp.attrib})
    dashboard["swcs"] = swcs
    dashboard["swc_count"] = len(swcs)

    # Interfaces
    interfaces = []
    for iface in (root.findall(".//autosar:SENDER-RECEIVER-INTERFACE", ns) +
                  root.findall(".//autosar:CLIENT-SERVER-INTERFACE", ns)):
        iface_name = safe_find(iface, "autosar:SHORT-NAME", ns)
        iface_uuid = iface.get("UUID", "N/A")
        iface_type = "Sender/Receiver" if iface.tag.endswith("SENDER-RECEIVER-INTERFACE") else "Client/Server"
        is_service = safe_find(iface, "autosar:IS-SERVICE", ns)
        category = safe_find(iface, "autosar:CATEGORY", ns)
        data_elements = []
        data_elems = iface.find("autosar:DATA-ELEMENTS", ns)
        if data_elems is not None:
            for var in data_elems.findall("autosar:VARIABLE-DATA-PROTOTYPE", ns):
                var_name = safe_find(var, "autosar:SHORT-NAME", ns)
                var_uuid = var.get("UUID", "N/A")
                type_ref_elem = var.find("autosar:TYPE-TREF", ns)
                type_ref_text = type_ref_elem.text.strip() if type_ref_elem is not None and type_ref_elem.text else "N/A"
                sw_data_def_props = None
                sd_elem = var.find("autosar:SW-DATA-DEF-PROPS", ns)
                if sd_elem is not None:
                    sw_data_def_props = ET.tostring(sd_elem, encoding="unicode")
                data_elements.append({
                    "name": var_name,
                    "uuid": var_uuid,
                    "type_ref": type_ref_text,
                    "sw_data_def_props": sw_data_def_props,
                    "attributes": var.attrib
                })
        interfaces.append({
            "name": iface_name,
            "uuid": iface_uuid,
            "type": iface_type,
            "is_service": is_service,
            "category": category,
            "data_elements": data_elements,
            "attributes": iface.attrib
        })
    dashboard["interfaces"] = interfaces
    dashboard["interface_count"] = len(interfaces)

    # Signals
    signals = []
    for signal in root.findall(".//autosar:I-SIGNAL", ns):
        name_elem = signal.find("autosar:SHORT-NAME", ns)
        name = name_elem.text.strip() if name_elem is not None and name_elem.text else "N/A"
        sys_sig_ref = signal.find("autosar:SYSTEM-SIGNAL-REF", ns)
        mapped_signal = sys_sig_ref.text.strip() if sys_sig_ref is not None and sys_sig_ref.text else "N/A"
        signals.append({
            "name": name,
            "mapped_signal": mapped_signal,
            "attributes": signal.attrib
        })
    dashboard["signals"] = signals
    dashboard["signal_count"] = len(signals)

    # Connectors
    connectors = []
    for conn in root.findall(".//autosar:ASSEMBLY-SW-CONNECTOR", ns):
        name = safe_find(conn, "autosar:SHORT-NAME", ns)
        provider = "N/A"
        requester = "N/A"
        context_refs = conn.findall(".//autosar:CONTEXT-COMPONENT-REF", ns)
        if context_refs:
            provider = context_refs[0].text.strip().split("/")[-1] if context_refs[0].text else "N/A"
        if len(context_refs) > 1:
            requester = context_refs[1].text.strip().split("/")[-1] if context_refs[1].text else "N/A"
        desc = None
        desc_elem = conn.find("autosar:DESC", ns)
        if desc_elem is not None:
            l2_elem = desc_elem.find("autosar:L-2", ns)
            if l2_elem is not None and l2_elem.text:
                desc = l2_elem.text.strip()
        connectors.append({
            "name": name,
            "provider": provider,
            "requester": requester,
            "description": desc,
            "attributes": conn.attrib
        })
    for conn in root.findall(".//autosar:DELEGATION-SW-CONNECTOR", ns):
        name = safe_find(conn, "autosar:SHORT-NAME", ns)
        provider = "N/A"
        if conn.find(".//autosar:INNER-PORT-IREF", ns) is not None:
            inner = conn.find(".//autosar:INNER-PORT-IREF//autosar:TARGET-P-PORT-REF", ns)
            if inner is not None and inner.text:
                provider = inner.text.strip().split("/")[-1]
        outer_port_elem = conn.find("autosar:OUTER-PORT-REF", ns)
        requester = outer_port_elem.text.strip().split("/")[-1] if outer_port_elem is not None and outer_port_elem.text else "N/A"
        connectors.append({
            "name": name,
            "provider": provider,
            "requester": requester,
            "attributes": conn.attrib
        })
    dashboard["connectors"] = connectors
    dashboard["connector_count"] = len(connectors)

    # Functional Details
    functional = []
    behaviors = root.findall(".//autosar:SWC-INTERNAL-BEHAVIOR", ns)
    for beh in behaviors:
        beh_name = safe_find(beh, "autosar:SHORT-NAME", ns)
        handle_term_val = safe_find(beh, "autosar:HANDLE-TERMINATION-AND-RESTART", ns)
        events_list = []
        events_elem = beh.find("autosar:EVENTS", ns)
        if events_elem is not None:
            for event in events_elem:
                event_type = event.tag.split('}')[-1] if '}' in event.tag else event.tag
                event_name = safe_find(event, "autosar:SHORT-NAME", ns)
                event_detail = {"type": event_type, "name": event_name, "attributes": event.attrib}
                if event_type == "TIMING-EVENT":
                    period = event.find("autosar:PERIOD", ns)
                    if period is not None and period.text:
                        event_detail["period"] = period.text.strip()
                desc_elem = event.find("autosar:DESC", ns)
                if desc_elem is not None:
                    l2_elem = desc_elem.find("autosar:L-2", ns)
                    if l2_elem is not None and l2_elem.text:
                        event_detail["description"] = l2_elem.text.strip()
                events_list.append(event_detail)
        runnables_list = []
        runnables_elem = beh.find("autosar:RUNNABLES", ns)
        if runnables_elem is not None:
            for runnable in runnables_elem.findall("autosar:RUNNABLE-ENTITY", ns):
                run_name = safe_find(runnable, "autosar:SHORT-NAME", ns)
                min_interval = safe_find(runnable, "autosar:MINIMUM-START-INTERVAL", ns)
                concurrently_val = safe_find(runnable, "autosar:CAN-BE-INVOKED-CONCURRENTLY", ns)
                data_read = []
                dr_access_elem = runnable.find("autosar:DATA-READ-ACCESSS", ns)
                if dr_access_elem is not None:
                    for va in dr_access_elem.findall("autosar:VARIABLE-ACCESS", ns):
                        va_name = safe_find(va, "autosar:SHORT-NAME", ns)
                        details = {}
                        av = va.find("autosar:ACCESSED-VARIABLE", ns)
                        if av is not None:
                            port_ref = safe_find(av, "autosar:PORT-PROTOTYPE-REF", ns)
                            target_data_ref = safe_find(av, "autosar:TARGET-DATA-PROTOTYPE-REF", ns)
                            details["port_ref"] = port_ref
                            details["target_data_ref"] = target_data_ref
                        data_read.append({"short_name": va_name, "details": details, "attributes": va.attrib})
                data_write = []
                dw_access_elem = runnable.find("autosar:DATA-WRITE-ACCESSS", ns)
                if dw_access_elem is not None:
                    for va in dw_access_elem.findall("autosar:VARIABLE-ACCESS", ns):
                        va_name = safe_find(va, "autosar:SHORT-NAME", ns)
                        details = {}
                        av = va.find("autosar:ACCESSED-VARIABLE", ns)
                        if av is not None:
                            port_ref = safe_find(av, "autosar:PORT-PROTOTYPE-REF", ns)
                            target_data_ref = safe_find(av, "autosar:TARGET-DATA-PROTOTYPE-REF", ns)
                            details["port_ref"] = port_ref
                            details["target_data_ref"] = target_data_ref
                        data_write.append({"short_name": va_name, "details": details, "attributes": va.attrib})
                runnables_list.append({
                    "name": run_name,
                    "min_interval": min_interval,
                    "concurrent": concurrently_val,
                    "data_read_access": data_read,
                    "data_write_access": data_write,
                    "attributes": runnable.attrib
                })
        functional.append({
            "behavior": beh_name,
            "handle_termination_and_restart": handle_term_val,
            "events": events_list,
            "runnables": runnables_list,
            "attributes": beh.attrib
        })
    dashboard["functional"] = functional

    # Diagnostic Details & Error Definitions
    diagnostic = []
    error_definitions = []
    for cs in root.findall(".//autosar:CLIENT-SERVER-INTERFACE", ns):
        iface_name = safe_find(cs, "autosar:SHORT-NAME", ns)
        possible_errors = cs.find("autosar:POSSIBLE-ERRORS", ns)
        errors = []
        if possible_errors is not None:
            for app_error in possible_errors.findall("autosar:APPLICATION-ERROR", ns):
                err_name = safe_find(app_error, "autosar:SHORT-NAME", ns)
                err_code = safe_find(app_error, "autosar:ERROR-CODE", ns)
                errors.append({"name": err_name, "code": err_code, "attributes": app_error.attrib})
                error_definitions.append({
                    "interface": iface_name,
                    "error_name": err_name,
                    "error_code": err_code,
                    "attributes": app_error.attrib
                })
        diagnostic.append({
            "interface": iface_name,
            "errors": errors,
            "attributes": cs.attrib
        })
    dashboard["diagnostic"] = diagnostic
    dashboard["error_definitions"] = error_definitions

    # Resource Details from SWC-IMPLEMENTATION
    resource = []
    for impl in root.findall(".//autosar:SWC-IMPLEMENTATION", ns):
        comp_name = safe_find(impl, "autosar:SHORT-NAME", ns)
        resource_elem = impl.find("autosar:RESOURCE-CONSUMPTION", ns)
        resource_name = safe_find(resource_elem, "autosar:SHORT-NAME", ns) if resource_elem is not None else "N/A"
        resource.append({
            "component": comp_name,
            "resource_consumption": resource_name,
            "attributes": impl.attrib
        })
    dashboard["resource"] = resource

    # System Mappings – SWC-to-Impl and Data Mappings
    system_mappings = []
    for mapping in root.findall(".//autosar:SYSTEM-MAPPING", ns):
        mapping_short = safe_find(mapping, "autosar:SHORT-NAME", ns)
        sw_impl_mappings = []
        sw_impl_mappings_elem = mapping.find("autosar:SW-IMPL-MAPPINGS", ns)
        if sw_impl_mappings_elem is not None:
            for swc_impl_mapping in sw_impl_mappings_elem.findall("autosar:SWC-TO-IMPL-MAPPING", ns):
                map_short = safe_find(swc_impl_mapping, "autosar:SHORT-NAME", ns)
                comp_impl_ref = swc_impl_mapping.find("autosar:COMPONENT-IMPLEMENTATION-REF", ns)
                comp_impl_ref_text = comp_impl_ref.text.strip() if comp_impl_ref is not None and comp_impl_ref.text else "N/A"
                comp_irefs = []
                comp_irefs_elem = swc_impl_mapping.find("autosar:COMPONENT-IREFS", ns)
                if comp_irefs_elem is not None:
                    for comp_iref in comp_irefs_elem.findall("autosar:COMPONENT-IREF", ns):
                        context = safe_find(comp_iref, "autosar:CONTEXT-COMPOSITION-REF", ns)
                        target = safe_find(comp_iref, "autosar:TARGET-COMPONENT-REF", ns)
                        comp_irefs.append({
                            "context": context,
                            "target_component_ref": target,
                            "attributes": comp_iref.attrib
                        })
                sw_impl_mappings.append({
                    "short_name": map_short,
                    "component_impl_ref": comp_impl_ref_text,
                    "component_irefs": comp_irefs,
                    "attributes": swc_impl_mapping.attrib
                })
        data_mappings = []
        data_mappings_elem = mapping.find("autosar:DATA-MAPPINGS", ns)
        if data_mappings_elem is not None:
            for mapping_elem in data_mappings_elem.findall("autosar:SENDER-RECEIVER-TO-SIGNAL-MAPPING", ns):
                data_element_iref = mapping_elem.find("autosar:DATA-ELEMENT-IREF", ns)
                context_comp = safe_find(data_element_iref, "autosar:CONTEXT-COMPOSITION-REF", ns) if data_element_iref is not None else "N/A"
                target_data_ref = safe_find(data_element_iref, "autosar:TARGET-DATA-PROTOTYPE-REF", ns) if data_element_iref is not None else "N/A"
                system_signal_ref = safe_find(mapping_elem, "autosar:SYSTEM-SIGNAL-REF", ns)
                data_mappings.append({
                    "context_composition": context_comp,
                    "target_data_prototype_ref": target_data_ref,
                    "system_signal_ref": system_signal_ref,
                    "attributes": mapping_elem.attrib
                })
        mapping_obj = {"short_name": mapping_short, "sw_impl_mappings": sw_impl_mappings, "attributes": mapping.attrib}
        if data_mappings:
            mapping_obj["data_mappings"] = data_mappings
        system_mappings.append(mapping_obj)
    dashboard["system_mappings"] = system_mappings

    # Communication Details – I-Signals and I-Signal I-PDU mappings
    i_signals = []
    for i_sig in root.findall(".//autosar:I-SIGNAL", ns):
        i_sig_name = safe_find(i_sig, "autosar:SHORT-NAME", ns)
        i_sig_uuid = i_sig.get("UUID", "N/A")
        sys_sig_ref = safe_find(i_sig, "autosar:SYSTEM-SIGNAL-REF", ns)
        i_signals.append({
            "name": i_sig_name,
            "uuid": i_sig_uuid,
            "system_signal_ref": sys_sig_ref,
            "attributes": i_sig.attrib
        })
    i_signal_ipdus = []
    for ipdu in root.findall(".//autosar:I-SIGNAL-I-PDU", ns):
        ipdu_name = safe_find(ipdu, "autosar:SHORT-NAME", ns)
        ipdu_uuid = ipdu.get("UUID", "N/A")
        mappings = []
        mappings_elem = ipdu.find("autosar:I-SIGNAL-TO-PDU-MAPPINGS", ns)
        if mappings_elem is not None:
            for mapping in mappings_elem.findall("autosar:I-SIGNAL-TO-I-PDU-MAPPING", ns):
                map_short = safe_find(mapping, "autosar:SHORT-NAME", ns)
                i_sig_ref = safe_find(mapping, "autosar:I-SIGNAL-REF", ns)
                mappings.append({"short_name": map_short, "i_signal_ref": i_sig_ref, "attributes": mapping.attrib})
        i_signal_ipdus.append({
            "name": ipdu_name,
            "uuid": ipdu_uuid,
            "mappings": mappings,
            "attributes": ipdu.attrib
        })
    dashboard["communication"] = {"i_signals": i_signals, "i_signal_ipdus": i_signal_ipdus}

    # Include the complete generic parse of the ARXML for extended analysis
    dashboard["full_generic_parse"] = parse_arxml_generic(xml_file_path)

    return dashboard

# ----------------------- New Route: Interactive 3D Diagram -----------------------
@app.route("/diagram3d/<filename>")
def diagram3d(filename):
    # Load the ARXML file from the upload folder.
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    G = parse_arxml_to_broader_composition_graph(file_path)
    # Use 3D spring layout with increased spacing.
    pos = nx.spring_layout(G, dim=3, k=5.0, seed=42)
    
    # Prepare node coordinates and attributes.
    node_list = list(G.nodes())
    x_nodes, y_nodes, z_nodes = [], [], []
    node_text, node_colors = [], []
    node_types = nx.get_node_attributes(G, "type")
    base_size = 30  # increased base marker size
    for node in node_list:
        x, y, z = pos[node]
        x_nodes.append(x)
        y_nodes.append(y)
        z_nodes.append(z)
        label = G.nodes[node].get("label", node)
        node_text.append(label)
        ntype = node_types.get(node, "Unknown")
        if ntype == "SWC":
            node_colors.append("skyblue")
        elif ntype == "Service":
            node_colors.append("lightgreen")
        elif ntype == "Interface":
            node_colors.append("orange")
        elif ntype == "Composition":
            node_colors.append("purple")
        elif ntype == "Port":
            node_colors.append("white")
        elif ntype == "Runnable":
            node_colors.append("#ffd1dc")
        elif ntype == "Event":
            node_colors.append("#ffebcc")
        else:
            node_colors.append("lightgray")
    
    # Prepare edge coordinates.
    edge_x, edge_y, edge_z = [], [], []
    for u, v, d in G.edges(data=True):
        x0, y0, z0 = pos[u]
        x1, y1, z1 = pos[v]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
        edge_z.extend([z0, z1, None])
    
    edge_trace = go.Scatter3d(
        x=edge_x, y=edge_y, z=edge_z,
        line=dict(width=3, color='black'),
        mode='lines',
        hoverinfo='none'
    )
    
    node_trace = go.Scatter3d(
        x=x_nodes, y=y_nodes, z=z_nodes,
        mode='markers+text',
        marker=dict(
            size=[base_size]*len(x_nodes),
            color=node_colors,
            opacity=0.9
        ),
        text=node_text,
        hoverinfo='text'
    )
    
    # Manual legend as annotation (can be toggled off if needed)
    legend_annotation = dict(
        x=0.1,
        y=0.9,
        xref="paper",
        yref="paper",
        text=("<b>Legend:</b><br>"
              "SWC: skyblue<br>"
              "Service: lightgreen<br>"
              "Interface: orange<br>"
              "Composition: purple<br>"
              "Port: white<br>"
              "Runnable: pink (#ffd1dc)<br>"
              "Event: light orange (#ffebcc)"),
        showarrow=False,
        bordercolor="black",
        borderwidth=1,
        bgcolor="white",
        opacity=0.9
    )
    
    fig = go.Figure(data=[edge_trace, node_trace],
                    layout=go.Layout(
                        title='Interactive 3D Diagram',
                        showlegend=False,
                        dragmode='orbit',
                        scene=dict(
                            xaxis=dict(showgrid=False, zeroline=False),
                            yaxis=dict(showgrid=False, zeroline=False),
                            zaxis=dict(showgrid=False, zeroline=False)
                        ),
                        margin=dict(b=20, l=5, r=5, t=40),
                        annotations=[legend_annotation],
                        hovermode='closest'
                    ))
    
    # Render the figure as HTML.
    html_str = fig.to_html(full_html=True, include_plotlyjs='cdn', div_id='plot3d')
    return Response(html_str, mimetype="text/html")

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
            filename = str(uuid.uuid4()) + ".arxml"
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            file.save(file_path)
            try:
                # Generate 2D composition diagram.
                G = parse_arxml_to_broader_composition_graph(file_path)
                try:
                    pos = nx.nx_agraph.graphviz_layout(G, prog="dot")
                except Exception as e:
                    pos = nx.spring_layout(G, k=5.0, iterations=200, seed=42)
                
                plt.figure(figsize=(16, 12))
                plt.axis('off')
                
                labels = nx.get_node_attributes(G, "label")
                node_types = nx.get_node_attributes(G, "type")
                node_colors = []
                for node in G.nodes():
                    ntype = node_types.get(node, "Unknown")
                    if ntype == "SWC":
                        node_colors.append("skyblue")
                    elif ntype == "Service":
                        node_colors.append("lightgreen")
                    elif ntype == "Interface":
                        node_colors.append("orange")
                    elif ntype == "Composition":
                        node_colors.append("purple")
                    elif ntype == "Port":
                        node_colors.append("white")
                    elif ntype == "Runnable":
                        node_colors.append("#ffd1dc")
                    elif ntype == "Event":
                        node_colors.append("#ffebcc")
                    else:
                        node_colors.append("lightgray")
                
                nx.draw_networkx_nodes(G, pos, node_size=2500, node_color=node_colors)
                nx.draw_networkx_labels(G, pos, labels=labels, font_size=10, font_weight='bold')
                nx.draw_networkx_edges(G, pos, arrows=True, arrowstyle="-|>", arrowsize=12)
                edge_labels = {(u, v): d["relation"] for u, v, d in G.edges(data=True) if "relation" in d}
                nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=9)
                
                plt.tight_layout()
                plt.margins(0.2)
                
                diagram_filename = str(uuid.uuid4()) + ".png"
                diagram_path = os.path.join(app.config["DIAGRAM_FOLDER"], diagram_filename)
                os.makedirs(app.config["DIAGRAM_FOLDER"], exist_ok=True)
                plt.savefig(diagram_path, dpi=150, bbox_inches='tight')
                plt.close()
                
                dashboard_data = parse_arxml_for_dashboard(file_path)
                
                os.makedirs("outputs", exist_ok=True)
                json_filename = os.path.splitext(filename)[0] + ".json"
                json_path = os.path.join("outputs", json_filename)
                with open(json_path, "w", encoding="utf-8") as json_file:
                    json.dump(dashboard_data, json_file, indent=2)
                
                # Do not remove the ARXML file so the 3D diagram can access it.
                return render_template("dashboard.html", diagram=diagram_filename, dashboard=dashboard_data, arxml_filename=filename)
            except Exception as e:
                flash(f"Error processing file: {e}")
                return redirect(request.url)
    return render_template("dashboard.html", diagram=None, dashboard=None, arxml_filename=None)

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
