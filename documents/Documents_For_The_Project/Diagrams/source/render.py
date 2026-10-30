import sys, os, importlib
sys.path.insert(0, os.path.dirname(__file__))
OUT = os.path.join(os.path.dirname(__file__), "out"); WORK = os.path.join(os.path.dirname(__file__), "work")
os.makedirs(OUT, exist_ok=True)
NAMES = {"fig01":"fig01_tiers","fig02":"fig02_deployment","fig03":"fig03_technical","fig04":"fig04_pipeline","fig05":"fig05_component",
 "fig06":"fig06_usecase","fig07":"fig07_userflow","fig08":"fig08_api","fig09":"fig09_er_app","fig10":"fig10_curated","fig11":"fig11_db_arch",
 "fig12":"fig12_seq_login","fig13":"fig13_seq_data","fig14":"fig14_seq_knowledge","fig15":"fig15_seq_pause","fig16":"fig16_seq_voice",
 "fig17":"fig17_rag_pipeline","fig18":"fig18_context_layer","fig19":"fig19_pipeline_package","fig20":"fig20_accuracy_guards"}
mods = [importlib.import_module(m) for m in ("figs_a","figs_b","figs_c") if os.path.exists(os.path.join(os.path.dirname(__file__), m+".py"))]
for key in sys.argv[1:]:
    for m in mods:
        if hasattr(m, key):
            p = getattr(m, key)().render(os.path.join(OUT, NAMES[key]+".png"), WORK); print("ok", p); break
