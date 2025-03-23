import xml.etree.ElementTree as ET
import json
from collections import defaultdict

# Initial JSON Dictionary with known AUTOSAR elements
ELEMENT_DICTIONARY = {
    "elements": {
        "ECU": {"description": "Electronic Control Unit", "visual": "RoundedRectangle", "color": "#FFD700"},
        "SW-COMPONENT": {"description": "Software Component", "visual": "Rectangle", "color": "#87CEEB"},
        "PORT": {"description": "Communication Port", "visual": "Circle", "color": "#32CD32"},
        "DATA-TYPE": {"description": "Data Type", "visual": "Ellipse", "color": "#FF4500"},
        "UNKNOWN": {"description": "Unknown Element", "visual": "Hexagon", "color": "#808080"}
    }
}

# Function to identify element type and update JSON if unknown
def identify_element(tag):
    known_elements = ELEMENT_DICTIONARY["elements"]
    if tag in known_elements:
        return known_elements[tag]
    
    # Mark unknown elements for user definition later
    if tag not in known_elements["UNKNOWN"]:
        known_elements["UNKNOWN"][tag] = {"description": "Unknown element", "visual": "Hexagon", "color": "#808080"}
        print(f"[INFO] Unknown element detected: {tag}")
    return known_elements["UNKNOWN"]

# Function to parse ARXML recursively and collect detailed structure
def parse_arxml(element, structure=None, depth=0):
    if structure is None:
        structure = defaultdict(lambda: {"attributes": {}, "children": {}, "depth": 0})

    tag = element.tag.split('}')[-1]  # Remove XML namespace
    attributes = element.attrib

    if tag not in structure:
        structure[tag] = {"attributes": attributes, "children": {}, "depth": depth}

    for child in element:
        child_tag = child.tag.split('}')[-1]
        structure[tag]["children"].setdefault(child_tag, []).append(parse_arxml(child, {}, depth + 1))

    return structure

# Main parsing logic
def main():
    arxml_file = input("Enter path to ARXML file: ").strip()
    output_json_file = "parsed_structure.json"
    element_json_file = "elements.json"

    try:
        tree = ET.parse(arxml_file)
        root = tree.getroot()

        # Parse ARXML structure
        structure = parse_arxml(root)
        print(json.dumps(structure, indent=4))

        # Write parsed structure to JSON file
        with open(output_json_file, 'w') as file:
            json.dump(structure, file, indent=4)

        # Write updated element dictionary to JSON dictionary
        with open(element_json_file, 'w') as file:
            json.dump(ELEMENT_DICTIONARY, file, indent=4)

        print(f"[SUCCESS] ARXML structure parsed and saved to {output_json_file}")
    except Exception as e:
        print(f"[ERROR] Failed to parse ARXML file: {e}")

if __name__ == "__main__":
    main()
