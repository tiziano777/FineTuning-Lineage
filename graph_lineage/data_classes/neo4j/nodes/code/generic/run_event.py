from ...base.event import Event

class RunEvent(Event):
    """ 
    Definizione DataObject prodotta da un Run(Case) (ACM Run Event).
    Questo DataObject è un oggetto generico che è usato per passare info al RunEventHandler(e: RunEvent), e può essere esteso con campi custom.
    
    Può:
    1) essere esteso con relativo custom edge + produced Artifact node. (current_run_id, edge_type, edge_payload_json, node_type, node_payload_json)
    2) Se event non produce output, può essere usato come nodo generico senza edge e senza Artifact node. (current_run_id)
    3) Oppure Se event produce un update del current case, invocare update sul current CaRun(Case). (current_run_id, update_payload_json)
    """
    pass