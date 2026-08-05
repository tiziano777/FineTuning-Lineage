from graph_lineage.data_classes.neo4j.nodes.base.enum.domain_type import DomainType

class ExperimentType(DomainType):
    """Tipo di Experiment."""
    TRAINING = "training"
    EVALUATION = "evaluation"
    INFERENCE = "inference"
    MERGING = "merging"