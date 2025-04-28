from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, json, datetime, math
from materials import materialer  # Importerar materialdata från materials.py

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Ändra till ett riktigt hemligt värde

# --- Databashantering ---
def get_db_connection():
    conn = sqlite3.connect('anbud.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS anbud (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT,
            data TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Beräkningsfunktion ---
def calculate_pipe(form):
    # Hämta valt basmaterial
    material_key = form.get("material")
    if not material_key:
        return None, "Välj ett basmaterial."
    
    # Hämta materialdata från materialregistret
    data = materialer.get(material_key)
    if not data:
        return None, "Valt material finns inte."
    
    # Hämta rörtyp (standard "Rör")
    pipe_type = form.get("pipe_type", "Rör")
    
    # Hämta längd i meter
    try:
        length_m = float(form.get("length") or 0)
    except ValueError:
        return None, "Ogiltigt värde för längd."
    
    # Hämta dimension (för rör) i mm
    try:
        dimension_mm = float(form.get("dimension") or 0)
    except ValueError:
        dimension_mm = 0

    # Basisolering (i mm) från basmaterialet
    base_insulation = data.get("isoleringstjocklek", 0)
    
    # --- Extra lager (t.ex. extra isolering eller tillbehör) ---
    material_layers = form.getlist("material_layer")
    layer_tillbehor_list = form.getlist("material_layer_tillbehor")
    extra_insulation = 0
    layers_info = []
    for i, mat_key in enumerate(material_layers):
        if mat_key:
            mat = materialer.get(mat_key)
            if mat:
                insulation = mat.get("isoleringstjocklek", 0)
                extra_insulation += insulation
                try:
                    tillbehor = float(layer_tillbehor_list[i]) if i < len(layer_tillbehor_list) and layer_tillbehor_list[i].strip() != "" else 0.0
                except ValueError:
                    tillbehor = 0.0
                layers_info.append({
                    "material_key": mat_key,
                    "insulation": insulation,
                    "artikelnamn": mat.get("artikelnamn"),
                    "tillbehor": tillbehor
                })
    
    # --- Beräkning av geometrin ---
    if pipe_type == "Rör":
        outer_diameter = (dimension_mm + 2 * (base_insulation + extra_insulation)) / 1000.0
        computed_amount = math.pi * outer_diameter * length_m
        dimension_display = dimension_mm
    else:
        try:
            height_mm = float(form.get("height") or 0)
            width_mm = float(form.get("width") or 0)
        except ValueError:
            height_mm = width_mm = 0
        outer_diameter = 0
        computed_amount = 2 * length_m * ((height_mm + width_mm + 4 * base_insulation) / 1000.0)
        dimension_display = ""
    
    # --- Prisberäkning ---
    price_per_unit = data.get("kostnad", 0)
    price = computed_amount * price_per_unit
    
    # --- Hantering av höjdtillägg ---
    try:
        hojdtillagg = float(form.get("hojdtillagg") or 0)
    except ValueError:
        hojdtillagg = 0.0
    # --- Arbetstid för isolering (grundtider) ---
    lop = data.get("lopmeter", 0)
    kvm_val = data.get("kvm", 0)
    work_time_isolering = (lop * length_m) + (kvm_val * computed_amount)
    if hojdtillagg > 0:
        work_time_isolering *= (1 + hojdtillagg / 100.0)

    # Hämta "grundtiden" direkt från materialet (ej multiplicerat med längd/area)
    isolering_grund_montering = data.get("lopmeter", 0)
    isolering_grund_tillverkning = data.get("kvm", 0)

    # Beräkna endast tilläggstid för montering
    isolering_tillagg_montering = isolering_grund_montering * (hojdtillagg / 100.0)


    # --- Övriga kvantiteter ---
    try:
        bojar = float(form.get("bojar") or 0)
    except ValueError:
        bojar = 0.0
    try:
        avstick = float(form.get("avstick") or 0)
    except ValueError:
        avstick = 0.0
    try:
        ventilkapor = float(form.get("ventilkapor") or 0)
    except ValueError:
        ventilkapor = 0.0
    try:
        flanskapa = float(form.get("flanskapa") or 0)
    except ValueError:
        flanskapa = 0.0
    try:
        rorstod = float(form.get("rorstod") or 0)
    except ValueError:
        rorstod = 0.0

    # --- Folieberäkning ---
    folie = form.get("folie") == "yes"
    if folie and pipe_type == "Rör":
        foil_area = computed_amount * 1.1  # 10% extra yta för folie
    else:
        foil_area = 0

  # --- Bandberäkning ---
    band = form.get("band") == "yes"
    if band and pipe_type == "Rör":
        circumference = math.pi * outer_diameter
        band_length = 3 * circumference * length_m
    else:
        band_length = 0

    # --- Beräkna bandets arbetstid ---
    if band and band_length > 0:
        # Exempel: 0,05 h per meter (grundtid för band)
        band_grundtid = 0.018  
        # Vi antar att arbetstiden för band är densamma som grundtiden
        band_arbetstid = band_length * 0.018   
    else:
        band_grundtid = 0
        band_arbetstid = 0

    # --- Hantera ytbeklädnad ---
    ytbekladnad_key = form.get("ytbekladnad")
    if ytbekladnad_key:
        yt_data = materialer.get(ytbekladnad_key)
        if yt_data:
            yt_cost_per_unit = yt_data.get("kostnad", 0)
            if pipe_type == "Rör":
                yt_area = math.pi * outer_diameter * length_m
            else:
                yt_area = 0
            yt_cost = yt_area * yt_cost_per_unit
        else:
            yt_cost = 0
            yt_area = 0
    else:
        yt_cost = 0
        yt_area = 0

    # --- Automatisk tejpberäkning (för lamellmatta eller Conlit Fire Mat) ---
    base_name_lower = data["artikelnamn"].lower()
    roll_length = 50
    if pipe_type == "Rör":
        circumference = math.pi * outer_diameter
        total_tape_length = length_m * circumference
        tejp_quantity = math.ceil(total_tape_length / roll_length)
    else:
        tejp_quantity = 0

    # --- Arbetstid för ytbekladnad ---
    if pipe_type == "Rör" and ytbekladnad_key:
        outer_diameter_mm = outer_diameter * 1000
        if "aluminium" in materialer[ytbekladnad_key]["artikelnamn"].lower():
            if outer_diameter_mm <= 250:
                grundtid_montering = 0.110
                grundtid_tillverkning = 0.04
                tillaggstid_montering = 0.068
            elif outer_diameter_mm <= 640:
                grundtid_montering = 0.07
                grundtid_tillverkning = 0.02
                tillaggstid_montering = 0.068
            else:
                grundtid_montering = 0.144
                grundtid_tillverkning = 0.08
                tillaggstid_montering = 0.068
        else:
            grundtid_montering = lop
            grundtid_tillverkning = kvm_val
            tillaggstid_montering = 0
        yt_area = math.pi * outer_diameter * length_m
        work_time_ytbekladnad = (grundtid_montering * length_m) + (grundtid_tillverkning * yt_area) + (tillaggstid_montering * yt_area)
    else:
        grundtid_montering = 0
        grundtid_tillverkning = 0
        tillaggstid_montering = 0
        work_time_ytbekladnad = 0

    # Hämta de nya dropdown-värdena
    distansjarn_material = form.get("distansjarn_material")
    distansjarn_procent = form.get("distansjarn_procent")
    distansring = form.get("distansring")

    # --- Spoltråd (för rör med lamellmatta eller Conlit Fire Mat) ---
    if pipe_type == "Rör" and ("lamellmatta" in base_name_lower or "conlit fire mat" in base_name_lower):
        spooltråd_m = 5 * math.pi * outer_diameter * length_m
        spooltråd_kg = spooltråd_m / 350
    else:
        spooltråd_m = 0
        spooltråd_kg = 0

    # Sätt ihop materialnamnet (inklusive extra lager om sådana finns)
    if layers_info:
        extra_names = ", ".join([layer["artikelnamn"] for layer in layers_info])
        display_material = f"{data['artikelnamn']} (+ {extra_names})"
    else:
        display_material = data["artikelnamn"]

    # Sammanställ alla beräknade värden i en result-dictionary
    result = {
        "pipe_type": pipe_type,
        "material": display_material,
        "material_key": material_key,
        "dimension": dimension_display,
        "length": length_m,
        "area": computed_amount,
        "hojdtillagg": hojdtillagg,
        "price": price,
        "work_time": work_time_isolering,
        "work_time_isolering": work_time_isolering,
        "work_time_ytbekladnad": work_time_ytbekladnad,
        "bojar": bojar,
        "avstick": avstick,
        "ventilkapor": ventilkapor,
        "flanskapa": flanskapa,
        "rorstod": rorstod,
        "layers": layers_info,
        "ytbekladnad_key": ytbekladnad_key,
        "ytbekladnad_cost": yt_cost,
        "ytbekladnad_area": yt_area,
        "grundtid_montering": grundtid_montering,
        "grundtid_tillverkning": grundtid_tillverkning,
        "tillaggstid_montering": tillaggstid_montering,
        "isolering_grund_montering": isolering_grund_montering,
        "isolering_grund_tillverkning": isolering_grund_tillverkning,
        "tejp_quantity": tejp_quantity,
        "spoltrad_m": spooltråd_m,
        "spoltrad_kg": spooltråd_kg,
        "folie": folie,
        "foil_area": foil_area,
        "band": band,
        "band_length": band_length,
        "band_grundtid": band_grundtid,
        "band_arbetstid": band_arbetstid,
        "distansjarn_material": distansjarn_material,
        "distansjarn_procent": distansjarn_procent,
        "distansring": distansring
    }
    return result, None

# --- Routes ---
@app.route('/')
def index():
    version = "v1.0"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return render_template("index.html", version=version, now=now)

@app.route('/new_bid', methods=['GET', 'POST'])
def new_bid():
    customers = load_customers_from_excel()  # Ladda kunder från filen/databasen

    if request.method == 'POST':
        bid_info = {
            "Anbudsnamn": request.form.get("bid_name"),
            "Anbudsnummer": request.form.get("bid_number"),
            "Kund": request.form.get("customer"),
            "Avdelning": request.form.get("department"),
            "Projektledare": request.form.get("project_manager"),
            "Kalkylansvarig": request.form.get("calculator"),
            "projekt_typ": request.form.get("projekt_typ")  # Save selected project type
        }
        session["bid_info"] = bid_info
        session["pipe_list"] = []
        return redirect(url_for("calculate"))

    return render_template("new_bid.html", customers=customers, departments=session.get("departments", []), project_managers=session.get("project_managers", []))

    
    # Hämta listor från session (om de inte finns, sätt några standardvärden)
    departments = session.get("departments", ["Stockholm", "Göteborg", "Malmö", "Uppsala"])
    project_managers = session.get("project_managers", [])
    
    return render_template("new_bid.html", customers=customers, departments=departments, project_managers=project_managers)



@app.route('/calculate', methods=['GET', 'POST'])
def calculate():
    if request.method == 'POST':
        pipe_data, error = calculate_pipe(request.form)
        if error:
            flash(error, "danger")
        else:
            pipe_list = session.get("pipe_list", [])
            pipe_list.append(pipe_data)
            session["pipe_list"] = pipe_list
            flash("Rörposten har lagts till i kalkylen.", "success")
        return redirect(url_for("calculate"))
    
    pipe_list = session.get("pipe_list", [])
    # Lista med basmaterialalternativ (visar artikelnummer och materialnamn)
    material_options = [
        (key, f'{data["artikelnr"]} - {data["artikelnamn"]}')
        for key, data in materialer.items()
    ]
    # Lista med ytbeklädnadsalternativ – visar endast materialnamnet
    ytbekladnad_materials = [
        (key, data["artikelnamn"])
        for key, data in materialer.items()
        if "aluminium" in data["artikelnamn"].lower()
    ]
    # Extract unique material types, excluding specific ones
    material_types = list({data["material typ"] for data in materialer.values() if data["material typ"] not in ["Tillbehör", "Aluminiumplåt", "Stålplåt"]})

    return render_template("calculate.html", 
                           pipe_list=pipe_list,
                           materials=material_options,
                           ytbekladnad_materials=ytbekladnad_materials,
                           materialer=materialer,
                           material_types=material_types)



@app.route('/materialspecifikation')
def materialspecifikation():
    from materials import materialer
    pipe_list = session.get("pipe_list", [])
    
    summary = {}
    
    # Processera basmaterial för varje recept
    for pipe in pipe_list:
        mat_key = pipe.get("material_key")
        group_key = "base_" + (mat_key if mat_key else "unknown")
        if pipe.get("pipe_type", "Rör") == "Rör":
            mängd_val = pipe.get("area", 0)
            enhet_val = "m²"
        else:
            mängd_val = pipe.get("length", 0)
            enhet_val = "m"
        if mat_key and mat_key in materialer:
            default_price = materialer[mat_key].get("kostnad", 0)
            artikelnr = materialer[mat_key].get("artikelnr", "Okänt")
            senast = materialer[mat_key].get("senast_uppdaterad", "Okänt")
        else:
            default_price = 0
            artikelnr = "Okänt"
            senast = "Okänt"
        used_price = pipe.get("adjusted_price", default_price)
        cost = mängd_val * used_price
        if group_key in summary:
            summary[group_key]["mängd"] += mängd_val
            summary[group_key]["total_cost"] += cost
        else:
            summary[group_key] = {
                "group_key": group_key,
                "artikelnamn": pipe.get("material", "Okänt material"),
                "artikelnr": artikelnr,
                "senast_uppdaterad": senast,
                "mängd": mängd_val,
                "enhet": enhet_val,
                "apris": default_price,
                "total_cost": cost
            }

        # Processera ytbeklädnad (om valt)
        if pipe.get("ytbekladnad_key"):
            yt_key = pipe.get("ytbekladnad_key")
            group_key_yt = "yt_" + (yt_key if yt_key else "unknown")
            # Använd den beräknade ytbeklädnadsarean som kvantitet
            yt_quantity = pipe.get("ytbekladnad_area", 0)
            if yt_key and yt_key in materialer:
                yt_default_price = materialer[yt_key].get("kostnad", 0)
                yt_artikelnr = materialer[yt_key].get("artikelnr", "Okänt")
                yt_senast = materialer[yt_key].get("senast_uppdaterad", "Okänt")
            else:
                yt_default_price = 0
                yt_artikelnr = "Okänt"
                yt_senast = "Okänt"
            yt_cost = pipe.get("ytbekladnad_cost", 0)
            if group_key_yt in summary:
                summary[group_key_yt]["mängd"] += yt_quantity
                summary[group_key_yt]["total_cost"] += yt_cost
            else:
                summary[group_key_yt] = {
                    "group_key": group_key_yt,
                    "artikelnamn": materialer[yt_key].get("artikelnamn", "Okänt material") if yt_key in materialer else "Okänt material",
                    "artikelnr": yt_artikelnr,
                    "senast_uppdaterad": yt_senast,
                    "mängd": yt_quantity,
                    "enhet": "m²",
                    "apris": yt_default_price,
                    "total_cost": yt_cost
 }
            # --- NYTT: Popnit-uppgifter ---
            # Endast om ytbeklädnads-materialet innehåller "aluminium"
            if "aluminium" in materialer[yt_key]["artikelnamn"].lower():
                group_key_popnit = "popnit"
                # Beräkna popnit: 10 ask per m² (popnit_ask = yt_area / 100)
                popnit_ask = (pipe.get("ytbekladnad_area", 0)) / 100
                popnit_default_price = materialer.get("85329500", {}).get("kostnad", 0)
                popnit_artnr = materialer.get("85329500", {}).get("artikelnr", "85329500")
                popnit_total = popnit_ask * popnit_default_price
                if group_key_popnit in summary:
                    summary[group_key_popnit]["mängd"] += popnit_ask
                    summary[group_key_popnit]["total_cost"] += popnit_total
                else:
                    summary[group_key_popnit] = {
                        "group_key": group_key_popnit,
                        "artikelnamn": "Popnit",
                        "artikelnr": popnit_artnr,
                        "senast_uppdaterad": "",  # Ange datum vid behov
                        "mängd": popnit_ask,
                        "enhet": "ask",
                        "apris": popnit_default_price,
                        "total_cost": popnit_total
                    }
        
        # Processera extra lager i receptet
        for layer in pipe.get("layers", []):
            layer_key = layer.get("material_key")
            group_key_layer = "layer_" + (layer_key if layer_key else "unknown")
            if layer_key and layer_key in materialer:
                layer_default_price = materialer[layer_key].get("kostnad", 0)
                layer_artikelnr = materialer[layer_key].get("artikelnr", "Okänt")
                layer_senast = materialer[layer_key].get("senast_uppdaterad", "Okänt")
            else:
                layer_default_price = 0
                layer_artikelnr = "Okänt"
                layer_senast = "Okänt"
            # Anta att kvantiteten för extra lager är summan av "insulation" och "tillbehor"
            extra_mängd = layer.get("insulation", 0) + layer.get("tillbehor", 0)
            used_price_layer = layer.get("adjusted_price", layer_default_price)
            layer_cost = extra_mängd * used_price_layer
            if group_key_layer in summary:
                summary[group_key_layer]["mängd"] += extra_mängd
                summary[group_key_layer]["total_cost"] += layer_cost
            else:
                summary[group_key_layer] = {
                    "group_key": group_key_layer,
                    "artikelnamn": materialer[layer_key]["artikelnamn"],
                    "artikelnr": layer_artikelnr,
                    "senast_uppdaterad": layer_senast,
                    "mängd": extra_mängd,
                    "enhet": "mm",
                    "apris": layer_default_price,
                    "total_cost": layer_cost
                }
        
        # Processera spoltråd om det finns (baserat på calculate_pipe)
        if pipe.get("spoltrad_kg", 0) > 0:
            group_key_spool = "spool"
            spool_quantity = pipe.get("spoltrad_kg", 0)
            spool_data = materialer.get("4023313", {})
            spool_default_price = spool_data.get("kostnad", 0)
            spool_artikelnr = spool_data.get("artikelnr", "Okänt")
            spool_senast = spool_data.get("senast_uppdaterad", "Okänt")
            spool_cost = spool_quantity * spool_default_price
            if group_key_spool in summary:
                summary[group_key_spool]["mängd"] += spool_quantity
                summary[group_key_spool]["total_cost"] += spool_cost
            else:
                summary[group_key_spool] = {
                    "group_key": group_key_spool,
                    "artikelnamn": spool_data.get("artikelnamn", "Spoltråd 0,70"),
                    "artikelnr": spool_artikelnr,
                    "senast_uppdaterad": spool_senast,
                    "mängd": spool_quantity,
                    "enhet": "kg",
                    "apris": spool_default_price,
                    "total_cost": spool_cost
                }
        
        # Processera tejp om det finns (exempel, om tejp används som extra lager)
        if pipe.get("tejp_quantity", 0) > 0:
            group_key_tejp = "tejp"
            tejp_quantity = pipe.get("tejp_quantity", 0)
            tejp_data = materialer.get("PTBCR07550", {})
            tejp_default_price = tejp_data.get("kostnad", 0)
            tejp_artikelnr = tejp_data.get("artikelnr", "Okänt")
            tejp_senast = tejp_data.get("senast_uppdaterad", "Okänt")
            tejp_cost = tejp_quantity * tejp_default_price
            if group_key_tejp in summary:
                summary[group_key_tejp]["mängd"] += tejp_quantity
                summary[group_key_tejp]["total_cost"] += tejp_cost
            else:
                summary[group_key_tejp] = {
                    "group_key": group_key_tejp,
                    "artikelnamn": tejp_data.get("artikelnamn", "Tejp"),
                    "artikelnr": tejp_artikelnr,
                    "senast_uppdaterad": tejp_senast,
                    "mängd": tejp_quantity,
                    "enhet": "rle",
                    "apris": tejp_default_price,
                    "total_cost": tejp_cost
                }
        
        # Processera folie om det finns (baserat på calculate_pipe)
        if pipe.get("foil_area", 0) > 0:
            group_key_folie = "folie"
            foil_quantity = pipe.get("foil_area", 0)
            # Hämta foliedatan med artikelnummer 4025571
            foil_data = materialer.get("4025571")
            if foil_data:
                foil_price = foil_data.get("kostnad", 0)
                foil_artikelnr = foil_data.get("artikelnr", "Okänt")
                foil_senast = foil_data.get("senast_uppdaterad", "Okänt")
                foil_name = foil_data.get("artikelnamn", "Folie")
            else:
                foil_price = 50.0
                foil_artikelnr = "4025571"
                foil_senast = "2025-03-05"
                foil_name = "Folie"
            foil_cost = foil_quantity * foil_price
            if group_key_folie in summary:
                summary[group_key_folie]["mängd"] += foil_quantity
                summary[group_key_folie]["total_cost"] += foil_cost
            else:
                summary[group_key_folie] = {
                    "group_key": group_key_folie,
                    "artikelnamn": foil_name,
                    "artikelnr": foil_artikelnr,
                    "senast_uppdaterad": foil_senast,
                    "mängd": foil_quantity,
                    "enhet": "m²",
                    "apris": foil_price,
                    "total_cost": foil_cost
                }
      # --- NYTT: Processera band (om det finns) ---
        if pipe.get("band") and pipe.get("band_length", 0) > 0:
            group_key_band = "band"
            band_length = pipe.get("band_length", 0)
            # Hämta banddata från materialer med artikelnummer 9556892
            band_data = materialer.get("9556892", {})
            band_price = band_data.get("kostnad", 0)
            band_artikelnr = band_data.get("artikelnr", "9556892")
            band_senast = band_data.get("senast_uppdaterad", "Okänt")
            if group_key_band in summary:
                summary[group_key_band]["mängd"] += band_length
                summary[group_key_band]["total_cost"] += band_length * band_price
            else:
                summary[group_key_band] = {
                    "group_key": group_key_band,
                    "artikelnamn": band_data.get("artikelnamn", "Band"),
                    "artikelnr": band_artikelnr,
                    "senast_uppdaterad": band_senast,
                    "mängd": band_length,
                    "enhet": "m",
                    "apris": band_price,
                    "total_cost": band_length * band_price
                }
    
    summary_list = []
    total_material_cost = 0
    for key, data in summary.items():
        total_material_cost += data["total_cost"]
        summary_list.append(data)
    
    return render_template("materialspecifikation.html", summary=summary_list, total_material_cost=total_material_cost)


@app.route('/save_bid', methods=['POST'])
def save_bid():
    bid_info = session.get("bid_info")
    pipe_list = session.get("pipe_list", [])
    if not bid_info or not pipe_list:
        flash("Anbudsinfo eller kalkyl saknas.", "danger")
        return redirect(url_for("calculate"))
    
    bid_data = {
        "bid_info": bid_info,
        "kalkyl": pipe_list
    }
    conn = get_db_connection()
    datum = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if "id" in bid_info and bid_info["id"]:
        # Uppdatera befintligt anbud
        conn.execute("UPDATE anbud SET datum = ?, data = ? WHERE id = ?",
                     (datum, json.dumps(bid_data), bid_info["id"]))
    else:
        # Skapa nytt anbud
        conn.execute("INSERT INTO anbud (datum, data) VALUES (?, ?)",
                     (datum, json.dumps(bid_data)))
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        bid_info["id"] = new_id
    conn.commit()
    conn.close()
    flash("Anbudet har sparats.", "success")
    session.pop("bid_info", None)
    session.pop("pipe_list", None)
    session.pop("default_material", None)
    return redirect(url_for("index"))


@app.route('/old_bids')
def old_bids():
    conn = get_db_connection()
    bids = conn.execute("SELECT id, datum, data FROM anbud ORDER BY id DESC").fetchall()
    conn.close()

    bids_list = []
    for bid in bids:
        bid_dict = dict(bid)
        data_dict = json.loads(bid_dict["data"])
        bid_info = data_dict.get("bid_info", {})

        bid_dict["anbudsnummer"] = bid_info.get("Anbudsnummer", bid_dict["id"])
        bid_dict["anbudsnamn"] = bid_info.get("Anbudsnamn", "Okänt")
        bid_dict["avdelning"] = bid_info.get("Avdelning", "")
        bid_dict["projektledare"] = bid_info.get("Projektledare", "")
        bid_dict["kalkylansvarig"] = bid_info.get("Kalkylansvarig", "")
        bid_dict["kund"] = bid_info.get("Kund", "")
        bid_dict["projekt_typ"] = bid_info.get("projekt_typ", "")

        bids_list.append(bid_dict)

    return render_template("old_bids.html", bids=bids_list)




@app.route('/bid/<int:bid_id>')
def bid_detail(bid_id):
    conn = get_db_connection()
    bid = conn.execute("SELECT id, datum, data FROM anbud WHERE id = ?", (bid_id,)).fetchone()
    conn.close()
    if bid:
        try:
            bid_data = json.loads(bid["data"])
        except Exception:
            bid_data = {"error": "Kunde inte läsa anbudsdata."}
        return render_template("bid_detail.html", bid=bid, bid_data=bid_data)
    else:
        flash("Anbudet hittades inte.", "danger")
        return redirect(url_for("old_bids"))


@app.route('/edit_bid/<int:bid_id>')
def edit_bid(bid_id):
    conn = get_db_connection()
    bid = conn.execute("SELECT id, datum, data FROM anbud WHERE id = ?", (bid_id,)).fetchone()
    conn.close()
    if bid:
        try:
            bid_data = json.loads(bid["data"])
        except Exception as e:
            flash("Kunde inte läsa anbudsdata.", "danger")
            return redirect(url_for("old_bids"))
        session["bid_info"] = bid_data.get("bid_info")
        session["pipe_list"] = bid_data.get("kalkyl")
        flash("Kalkylen har laddats och du kan nu arbeta med den.", "success")
        return redirect(url_for("calculate"))
    else:
        flash("Anbudet hittades inte.", "danger")
        return redirect(url_for("old_bids"))
@app.route('/edit_pipe/<int:index>', methods=['GET','POST'])
def edit_pipe(index):
    pipe_list = session.get("pipe_list", [])
    if not (0 <= index < len(pipe_list)):
        flash("Ogiltigt index, kunde inte redigera receptet.", "danger")
        return redirect(url_for("calculate"))

    if request.method == 'POST':
        # Hämta befintlig post
        pipe_data = pipe_list[index]
        # Uppdatera med nya värden
        pipe_type = request.form.get("pipe_type", "Rör")
        try:
            length_m = float(request.form.get("length", 0))
        except ValueError:
            length_m = 0
        
        pipe_data["pipe_type"] = pipe_type
        pipe_data["length"] = length_m
        pipe_data["dimension"] = request.form.get("dimension", "")
        pipe_data["hojdtillagg"] = float(request.form.get("hojdtillagg") or 0)
        # ... eventuellt fler fält ...
        
        # Spara tillbaka
        pipe_list[index] = pipe_data
        session["pipe_list"] = pipe_list
        flash("Receptet har uppdaterats.", "success")
        return redirect(url_for("calculate"))
    
    # GET => visa ett formulär
    pipe_data = pipe_list[index]
    return render_template("edit_pipe.html", pipe=pipe_data, pipe_index=index)

@app.route('/remove_pipe/<int:index>', methods=['POST'])
def remove_pipe(index):
    pipe_list = session.get("pipe_list", [])
    if 0 <= index < len(pipe_list):
        pipe_list.pop(index)
        session["pipe_list"] = pipe_list
        flash("Receptet har tagits bort.", "success")
    else:
        flash("Ogiltigt index, kunde inte ta bort receptet.", "danger")
    return redirect(url_for("calculate"))
@app.route('/detailed_calculations')
def detailed_calculations():
    pipe_list = session.get("pipe_list", [])
    total_material_cost = 0.0
    total_work_time = 0.0

    for pipe in pipe_list:
        # Tejp
        tape_cost = 0
        if pipe.get("tejp_quantity"):
            if pipe.get("material") and ("lamellmatta" in pipe.get("material", "").lower()):
                tape_cost = pipe["tejp_quantity"] * materialer["9556523"]["kostnad"]
            elif pipe.get("material") and ("conlit fire mat" in pipe.get("material", "").lower()):
                tape_cost = pipe["tejp_quantity"] * materialer["PTBCR07550"]["kostnad"]

        # Spoltråd
        spool_cost = pipe.get("spoltrad_kg", 0) * materialer["4023313"]["kostnad"]

        # Band
        band_cost = 0
        if pipe.get("band"):
            band_cost = pipe.get("band_length", 0) * materialer["9556892"]["kostnad"]

        # Folie
        foil_area = pipe.get("foil_area", 0)
        folie_cost = foil_area * materialer["4025571"]["kostnad"]

        # Räkna ut total materialkostnad för raden med full precision
        row_total = (
            pipe.get("price", 0) +
            pipe.get("ytbekladnad_cost", 0) +
            tape_cost +
            spool_cost +
            band_cost +
            folie_cost
        )
        # Avrunda varje rads total till 0 decimaler och lägg till i den totala summan
        total_material_cost += round(row_total, 0)

# Beräkna total arbetstid för receptet (isolering + ytbeklädnad + band + folie)
    total_work_time = 0.0
    for pipe in pipe_list:
        # Arbetstid för isolering och ytbeklädnad
        pipe_total_work = pipe.get("work_time_isolering", 0) + pipe.get("work_time_ytbekladnad", 0)
        # Lägg till band-arbetstid (om den finns)
        pipe_total_work += pipe.get("band_arbetstid", 0)
        # Lägg till foliearbetstid om folien är vald
        if pipe.get("folie"):
            pipe_total_work += (0.03 * pipe.get("length", 0) + 0.049 * pipe.get("area", 0))
        total_work_time += pipe_total_work

    return render_template("detailed_calculations.html",
                           pipe_list=pipe_list,
                           materialer=materialer,
                           total_material_cost=total_material_cost,
                           total_work_time=total_work_time)

@app.route('/sammanstallning')
def sammanstallning():
    bid_info = session.get("bid_info", {})
    pipe_list = session.get("pipe_list", [])
    datum_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Materialkostnader
    total_isolering = sum(p.get("price", 0) for p in pipe_list)
    total_ytbekladnad = sum(p.get("ytbekladnad_cost", 0) for p in pipe_list)
    tape_price = materialer.get("PTBCR07550", {}).get("kostnad", 0)
    spool_price = materialer.get("4023313", {}).get("kostnad", 0)
    total_tape_cost = sum(p.get("tejp_quantity", 0) * tape_price for p in pipe_list)
    total_spool_cost = sum(p.get("spoltrad_kg", 0) * spool_price for p in pipe_list)
    total_tillbehor = total_tape_cost + total_spool_cost
    total_material_cost = total_isolering + total_ytbekladnad + total_tillbehor

    # Arbetstid (beräknad från receptet)
    total_work_time_calc = 0.0
    for pipe in pipe_list:
        pipe_total_work = pipe.get("work_time_isolering", 0) + pipe.get("work_time_ytbekladnad", 0)
        pipe_total_work += pipe.get("band_arbetstid", 0)
        if pipe.get("folie"):
            pipe_total_work += (0.03 * pipe.get("length", 0) + 0.049 * pipe.get("area", 0))
        total_work_time_calc += pipe_total_work

    # Hämta multiplikator, höjdtillägg och timtid – med defaultvärden
    multiplikator = float(session.get("multiplikator") or 1)
    hoejdtillaeg = float(session.get("hoejdtillaeg") or 0)  # i procent
    timtid = float(session.get("timtid") or 0)             # extra timmar att lägga till

    # Beräkna total arbetstid med nya värden
    total_work_time = total_work_time_calc * multiplikator * (1 + hoejdtillaeg/100) + timtid

    # Timlön
    hourly_wage = float(session.get("hourly_wage") or 252)
    labor_cost_per_hour = hourly_wage * 1.70
    total_labor_cost = total_work_time * labor_cost_per_hour

    # UE‑kostnader
    ue_cost = float(session.get("ue_cost") or 0)
    ue_hours = float(session.get("ue_hours") or 0)
    ue_montage = float(session.get("ue_montage") or 0)
    ue_tillverkning = float(session.get("ue_tillverkning") or 0)
    total_ue_cost = ue_cost + ue_hours + ue_montage + ue_tillverkning

    diverse_cost = total_material_cost * 0.015
    servicebil_days = float(session.get("servicebil_days") or 0)
    servicebil_cost = servicebil_days * 400

    total_work_cost = total_labor_cost + total_ue_cost + diverse_cost + servicebil_cost

    coverage_percentage = float(session.get("coverage_percentage") or 0)
    coverage_rate = coverage_percentage / 100.0
    final_price = (total_material_cost + total_work_cost) / (1 - coverage_rate) if coverage_rate < 1 else 0

    total_length = sum(p.get("length", 0) for p in pipe_list)
    labor_cost_per_meter = total_length > 0 and (total_labor_cost / total_length) or 0
    final_price_per_meter = total_length > 0 and (final_price / total_length) or 0

    return render_template("sammanstallning.html",
                           bid_info=bid_info,
                           datum=datum_str,
                           total_isolering=total_isolering,
                           total_ytbekladnad_cost=total_ytbekladnad,
                           total_accessories=total_tillbehor,
                           total_material_cost=total_material_cost,
                           total_work_time_calc=total_work_time_calc,
                           multiplikator=multiplikator,
                           hoejdtillaeg=hoejdtillaeg,
                           timtid=timtid,
                           total_work_time=total_work_time,
                           hourly_wage=hourly_wage,
                           labor_cost_per_hour=labor_cost_per_hour,
                           total_labor_cost=total_labor_cost,
                           ue_cost=ue_cost,
                           ue_hours=ue_hours,
                           ue_montage=ue_montage,
                           ue_tillverkning=ue_tillverkning,
                           total_ue_cost=total_ue_cost,
                           diverse_cost=diverse_cost,
                           servicebil_days=servicebil_days,
                           servicebil_cost=servicebil_cost,
                           total_work_cost=total_work_cost,
                           coverage_percentage=coverage_percentage,
                           final_price=final_price,
                           total_length=total_length,
                           labor_cost_per_meter=labor_cost_per_meter,
                           final_price_per_meter=final_price_per_meter,
                           notering_values=session.get("notering_values"))


@app.route('/update_sammanstallning', methods=['POST'])
def update_sammanstallning():
    session["hourly_wage"] = request.form.get("hourly_wage", "252")
    session["extra_work_hours"] = request.form.get("extra_work_hours", "0")
    session["coverage_percentage"] = request.form.get("coverage_percentage", "0")
    session["ue_cost"] = request.form.get("ue_cost", "0")
    session["ue_hours"] = request.form.get("ue_hours", "0")
    session["ue_montage"] = request.form.get("ue_montage", "0")
    session["ue_tillverkning"] = request.form.get("ue_tillverkning", "0")
    session["servicebil_days"] = request.form.get("servicebil_days", "0")
    flash("Ändringar sparade.", "success")
    return redirect(url_for("sammanstallning"))


@app.template_filter()
def thousandspace(value):
    """
    Formaterar ett numeriskt värde med tusentalsavgränsare som mellanslag.
    ex: 290321 -> 290 321
    """
    try:
        val = float(value)
        s = f"{val:,.0f}"  # ex '290,321'
        s = s.replace(",", " ")
        return s
    except (ValueError, TypeError):
        return value


import pandas as pd
import os
from flask import Flask, render_template, request, redirect, url_for, flash

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

CUSTOMER_FILE = os.path.join(UPLOAD_FOLDER, "customers.xlsx")

# Läs in kunder från Excel-fil
def load_customers_from_excel():
    if not os.path.exists(CUSTOMER_FILE):
        return []
    
    df = pd.read_excel(CUSTOMER_FILE, dtype=str).fillna("")
    customers = df.to_dict(orient='records')  
    return customers

# Uppdatera kunddatabasen från en ny Excel-fil
def update_customers(file_path):
    if not os.path.exists(CUSTOMER_FILE):
        df_old = pd.DataFrame()
    else:
        df_old = pd.read_excel(CUSTOMER_FILE, dtype=str).fillna("")

    df_new = pd.read_excel(file_path, dtype=str).fillna("")

    # Slå ihop gamla och nya kunder, baserat på "Kundnr"
    df_merged = pd.concat([df_old, df_new]).drop_duplicates(subset=["Kundnr"], keep="last")

    # Spara den uppdaterade listan
    df_merged.to_excel(CUSTOMER_FILE, index=False)
    return len(df_new), len(df_merged) - len(df_old)

# Route för att ladda upp och uppdatera kunder
@app.route('/upload_customers', methods=['POST'])
def upload_customers():
    if 'file' not in request.files:
        flash('Ingen fil vald', 'danger')
        return redirect(request.url)

    file = request.files['file']
    
    if file.filename == '':
        flash('Ingen fil vald', 'danger')
        return redirect(request.url)

    if file:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], "temp_customers.xlsx")
        file.save(file_path)

        new_entries, updated_entries = update_customers(file_path)

        flash(f'Kundlistan har uppdaterats! {new_entries} nya kunder, {updated_entries} uppdaterade.', 'success')

    return redirect(url_for('customers'))

# Route för att visa kundsidan
@app.route('/customers')
def customers():
    customers = load_customers_from_excel()
    return render_template('customers.html', customers=customers)
@app.route('/redigera/<int:bid_id>', methods=['GET'])
def redigera_anbud(bid_id):
    conn = get_db_connection()
    bid = conn.execute("SELECT id, datum, data FROM anbud WHERE id = ?", (bid_id,)).fetchone()
    conn.close()
    if not bid:
        flash("Anbudet hittades inte.", "danger")
        return redirect(url_for("old_bids"))
    
    try:
        bid_data = json.loads(bid["data"])
    except Exception:
        bid_data = {}
    
    # Lägg till anbudets id i bid_info
    bid_info = bid_data.get("bid_info", {})
    bid_info["id"] = bid["id"]
    session["bid_info"] = {
        "Anbudsnamn": bid_info.get("Anbudsnamn", ""),
        "Anbudsnummer": bid_info.get("Anbudsnummer", ""),
        "Avdelning": bid_info.get("Avdelning", ""),
        "Projektledare": bid_info.get("Projektledare", ""),
        "Kund": bid_info.get("Kund", ""),
        "Kalkylansvarig": bid_info.get("Kalkylansvarig", ""),
        "id": bid_info.get("id")  # Lägg med id:t
    }
    session["pipe_list"] = bid_data.get("kalkyl", [])
    
    flash("Kalkylen och anbudsinfo har laddats. Du kan nu bygga om receptet.", "success")
    return redirect(url_for("calculate"))


@app.route('/delete_bid/<int:bid_id>', methods=['POST'])
def delete_bid(bid_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM anbud WHERE id = ?", (bid_id,))
    conn.commit()
    conn.close()
    flash("Anbudet har raderats.", "success")
    return redirect(url_for("old_bids"))

@app.route('/departments', methods=['GET', 'POST'])
def departments():
    # Nya avdelningar att lägga till
    new_departments = [
        "4 Stenungsund", "8 Stockholm","53 Kristianstad/Malmö",
        "2 Linköping", "87 Gävle", "89 Luleå", "31 Halmstad", "1 Norrköping",
        "60 Sundsvall", "90 Kiruna", "41 Göteborg", "7 Örebro", "82 Örnsköldsvik", "86 Örnsköldsvik", "55 Projektgruppen", "Kalkyl"
    ]

    # Uppdatera sessionen med de nya avdelningarna
    session["departments"] = new_departments

    if request.method == "POST":
        new_department = request.form.get("new_department")
        if new_department and new_department not in session["departments"]:
            session["departments"].append(new_department)
            flash("Ny avdelning tillagd.", "success")
        return redirect(url_for("departments"))

    return render_template("departments.html", departments=session["departments"])

@app.route('/delete_department/<string:dept_name>', methods=['POST'])
def delete_department(dept_name):
    departments = session.get("departments", [])
    if dept_name in departments:
        departments.remove(dept_name)
        session["departments"] = departments
        flash(f"Avdelningen '{dept_name}' har raderats.", "success")
    else:
        flash("Avdelning hittades inte.", "danger")
    return redirect(url_for("departments"))

@app.route('/project_managers', methods=['GET', 'POST'])
def project_managers():
    # Kontrollera om sessionen redan innehåller projektledare
    if "project_managers" not in session:
        session["project_managers"] = [
            {"name": "Mikael Östman", "department": "Business Controller"},
            {"name": "Peter Ericsson", "department": "Säljchef / Sales Manager"},
            {"name": "Robert Nordin", "department": "Inköpschef / Head of Procurement"},
            {"name": "Hans Flemsten", "department": "Kalkylchef / Calculation Manager"},
            {"name": "Kicki Karlsson", "department": "Calculation & Marketing Coordinator"},
            {"name": "Tim Paar", "department": "Kalkylator / Programutvecklare"},
            {"name": "Pawel Nawrocki", "department": "Industri isolering"},
            {"name": "Kai Kaukonen", "department": "Projektsupport"},
            {"name": "Per Persson", "department": "Industri isolering, VVS – Vent isolering"},
            {"name": "Mikael Jonsson", "department": "VVS-Vent isolering"},
            {"name": "Joachim Hallin", "department": "Industri isolering"},
            {"name": "Mattias Tiensuu", "department": "Industri isolering, VVS – Vent isolering"},
            {"name": "Christer Eriksson", "department": "Industri isolering"},
            {"name": "Kent Westerlund", "department": "Industri isolering"},
            {"name": "Kjell-Gunnar Ehn", "department": "VVS-Vent isolering"},
            {"name": "Keijo Korvala", "department": "Industri isolering byggplåt"},
            {"name": "Linus Dahlberg", "department": "Industri isolering"},
            {"name": "Mattias Uppling", "department": "Industri isolering, VVS – Vent isolering"},
            {"name": "Sami Kultanen", "department": "Industri isolering, VVS – Vent isolering"},
            {"name": "Jonas Åsten", "department": "Industri isolering, VVS – Vent isolering"}
        ]

    pms = session.get("project_managers")
    departments = session.get("departments", ["Stockholm", "Göteborg", "Malmö", "Uppsala"])

    if request.method == "POST":
        new_manager = request.form.get("new_manager")
        dept = request.form.get("department")
        if new_manager:
            pms.append({"name": new_manager, "department": dept})
            session["project_managers"] = pms
            flash("Ny projektledare tillagd.", "success")
        return redirect(url_for("project_managers"))

    return render_template("project_managers.html", project_managers=pms, departments=departments)


@app.route('/update_pm_department/<int:index>', methods=['POST'])
def update_pm_department(index):
    new_dept = request.form.get("department")
    pms = session.get("project_managers", [])

    # Debug: Logga inkommande data och sessionens status
    print(f"Inkommande index: {index}")
    print(f"Inkommande avdelning: {new_dept}")
    print(f"Projektledare före uppdatering: {pms}")

    if 0 <= index < len(pms):
        pms[index]["department"] = new_dept
        session["project_managers"] = pms  # Uppdatera sessionen
        session.modified = True  # Säkerställ att sessionen sparas
        flash(f"Projektledaren '{pms[index]['name']}' har kopplats till avdelningen {new_dept}.", "success")
    else:
        flash(f"Projektledare hittades inte (index: {index}, antal: {len(pms)}).", "danger")

    # Debug: Logga sessionens status efter uppdatering
    print(f"Projektledare efter uppdatering: {session.get('project_managers')}")

    return redirect(url_for("project_managers"))

@app.route('/delete_project_manager/<int:index>', methods=['POST'])
def delete_project_manager(index):
    pms = session.get("project_managers", [])
    if 0 <= index < len(pms):
        removed = pms.pop(index)
        if isinstance(removed, dict):
            flash(f"Projektledaren '{removed['name']}' har raderats.", "success")
        else:
            flash(f"Projektledaren '{removed}' har raderats.", "success")
    else:
        flash(f"Projektledare hittades inte (index: {index}, antal: {len(pms)}).", "danger")
    session["project_managers"] = pms
    return redirect(url_for("project_managers"))


@app.route('/copy_recipe', methods=['POST'])
def copy_recipe():
    pipe_list = session.get("pipe_list", [])
    if pipe_list:
        # Hämta det senaste receptet
        last_recipe = pipe_list[-1]
        # Skapa en kopia (en enkel copy)
        new_recipe = last_recipe.copy()
        # Lägg till kopian i översikten
        pipe_list.append(new_recipe)
        # Spara det valda materialet för nästa recept
        session["default_material"] = new_recipe.get("material_key")
        session["pipe_list"] = pipe_list
        flash("Receptet har kopierats och lagts till i översikten.", "success")
    else:
        flash("Inget recept att kopiera.", "danger")
    return redirect(url_for("calculate"))


@app.route('/save_adjusted_prices', methods=['POST'])
def save_adjusted_prices():
    form_data = request.form.to_dict()
    pipe_list = session.get("pipe_list", [])
    # Gå igenom varje nyckel i formuläret
    for key, val in form_data.items():
        if key.startswith("adjusted_price_"):
            try:
                # Om ett värde är ifyllt, konvertera till float; annars låt det gamla värdet vara kvar.
                adjusted_price = float(val) if val.strip() != "" else None
            except ValueError:
                adjusted_price = None
            group_key = key[len("adjusted_price_"):]  # Exempel: "base_123456" eller "layer_4023313"
            if group_key.startswith("base_"):
                material_key = group_key[len("base_"):]
                for pipe in pipe_list:
                    if pipe.get("material_key") == material_key:
                        # Om inget nytt värde anges, gör ingenting (behåll tidigare sparade värdet)
                        if adjusted_price is not None:
                            pipe["adjusted_price"] = adjusted_price
            elif group_key.startswith("layer_"):
                material_key = group_key[len("layer_"):]
                for pipe in pipe_list:
                    layers = pipe.get("layers", [])
                    for layer in layers:
                        if layer.get("material_key") == material_key:
                            if adjusted_price is not None:
                                layer["adjusted_price"] = adjusted_price
    session["pipe_list"] = pipe_list
    flash("Justerade priser sparade i anbudet.", "success")
    return redirect(url_for("materialspecifikation"))

@app.route('/update_overview', methods=['POST'])
def update_overview():
    pipe_list = session.get("pipe_list", [])
    # Uppdatera endast de rader som finns i pipe_list
    for i, pipe in enumerate(pipe_list):
        # Använd request.form.get() med defaultvärde, så att tomma fält inte ger fel
        pipe['objekt'] = request.form.get(f"objekt_{i}", pipe.get('objekt', ''))
        pipe['sektion'] = request.form.get(f"sektion_{i}", pipe.get('sektion', ''))
    session["pipe_list"] = pipe_list
    flash("Ändringarna har sparats.", "success")
    return redirect(url_for("calculate"))


@app.route('/new_material', methods=['GET', 'POST'])
def new_material():
    if request.method == 'POST':
        try:
            # Hämta värden från formuläret
            artikelnr = request.form.get("artikelnr")
            artikelnamn = request.form.get("artikelnamn")
            material_typ = request.form.get("material_typ")  # Uppdaterad: nyckel för material typ
            diameter = request.form.get("diameter")
            isoleringstjocklek = request.form.get("isoleringstjocklek")
            leverantör = request.form.get("leverantör")
            enhet = request.form.get("enhet")
            kostnad = request.form.get("kostnad")
            lopmeter = request.form.get("lopmeter")
            kvm = request.form.get("kvm")
            senast_uppdaterad = datetime.datetime.now().strftime("%Y-%m-%d")

            # Hantera numeriska fält säkert
            try:
                kostnad = float(kostnad.replace(",", ".")) if kostnad else 0
                isoleringstjocklek = float(isoleringstjocklek) if isoleringstjocklek else 0
                lopmeter = float(lopmeter) if lopmeter else 0
                kvm = float(kvm) if kvm else 0
            except ValueError:
                kostnad, isoleringstjocklek, lopmeter, kvm = 0, 0, 0, 0  # Om fel, sätt till 0

            # Skapa nytt material-dictionary med "material typ" istället för "tillverkare"
            new_mat = {
                "artikelnr": artikelnr,
                "artikelnamn": artikelnamn,
                "material typ": material_typ,
                "diameter": diameter,
                "isoleringstjocklek": isoleringstjocklek,
                "leverantör": leverantör,
                "enhet": enhet,
                "kostnad": kostnad,
                "lopmeter": lopmeter,
                "kvm": kvm,
                "senast_uppdaterad": senast_uppdaterad
            }

            # Hämta materialer från session om de finns, annars använd materials.py
            materials_dict = session.get("materialer", {})

            # Lägg till nytt material
            materials_dict[artikelnr] = new_mat
            session["materialer"] = materials_dict
            session.modified = True  # 🔥 Viktigt för att spara sessionen!

            flash("Nytt material tillagt.", "success")
            return redirect(url_for("show_materials"))

        except Exception as e:
            flash(f"Ett fel uppstod: {e}", "danger")
            print("Fel i new_material:", e)  # Logga felet i terminalen

    return render_template("new_material.html")

@app.route('/update_material_sheet', methods=['POST'])
def update_material_sheet():
    # Loopar igenom alla nycklar i formuläret
    for key, value in request.form.items():
        if key.startswith("material_"):
            artikelnr = key.split("material_")[1]
            if artikelnr in materialer:
                materialer[artikelnr]["material typ"] = value
        elif key.startswith("spill_"):
            artikelnr = key.split("spill_")[1]
            if artikelnr in materialer:
                materialer[artikelnr]["spill"] = value
        elif key.startswith("senast_uppdaterad_"):
            artikelnr = key.split("senast_uppdaterad_")[1]
            if artikelnr in materialer:
                materialer[artikelnr]["senast_uppdaterad"] = value
    flash("Hela materialbladet har uppdaterats.", "success")
    return redirect(url_for("show_materials"))

@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now}


@app.route('/materials')
def show_materials():
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    return render_template("materials.html", materialer=materialer, current_date=current_date)


@app.route('/save_notering', methods=['POST'])
def save_notering():
    notering_values = {
        "isolering": request.form.get("notering_isolering", ""),
        "ytbekladnad": request.form.get("notering_ytbekladnad", ""),
        "tillbehor": request.form.get("notering_tillbehor", ""),
        "total": request.form.get("notering_total", "")
    }
    session["notering_values"] = notering_values
    flash("Noteringar sparade.", "success")
    return redirect(url_for("sammanstallning"))


@app.route('/grundinstallningar', methods=['GET', 'POST'])
def grundinstallningar():
    if request.method == 'POST':
        session['euro_kurs'] = request.form.get('euro_kurs', '0')
        session['ue_pris'] = request.form.get('ue_pris', '0')
        session['diverse_forbrukning'] = request.form.get('diverse_forbrukning', '0')
        session['timlon'] = request.form.get('timlon', '0')
        flash('Grundinställningar sparade.', 'success')
        return redirect(url_for('grundinstallningar'))

    return render_template('grundinstallningar.html', 
                           euro_kurs=session.get('euro_kurs', ''), 
                           ue_pris=session.get('ue_pris', ''), 
                           diverse_forbrukning=session.get('diverse_forbrukning', ''), 
                           timlon=session.get('timlon', ''))


if __name__ == '__main__':
    app.run(debug=True)
