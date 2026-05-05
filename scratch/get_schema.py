import json
from pandasai.data_loader.semantic_layer_schema import SemanticLayerSchema

# Generate the full JSON schema as defined by the code
schema = SemanticLayerSchema.model_json_schema()

print(json.dumps(schema, indent=2))
