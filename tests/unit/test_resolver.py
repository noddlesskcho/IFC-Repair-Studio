import unittest

from ifc_context_repair.context_index import SemanticIndex
from ifc_context_repair.models import ContextInfo, Status
from ifc_context_repair.resolver import resolve_context


class Entity:
    def __init__(self, step_id, kind, **attributes):
        self._id, self._kind = step_id, kind
        self.__dict__.update(attributes)

    def id(self): return self._id
    def is_a(self): return self._kind


def context(step_id, identifier):
    return Entity(step_id, "IfcGeometricRepresentationSubContext",
                  ContextIdentifier=identifier, ContextType="Model", TargetView="MODEL_VIEW")


class ResolverTests(unittest.TestCase):
    def setup_index(self, identifiers, representation_identifier="Body"):
        rep = Entity(10, "IfcShapeRepresentation", RepresentationIdentifier=representation_identifier,
                     RepresentationType="SweptSolid", Items=[Entity(11, "IfcExtrudedAreaSolid")])
        owner = Entity(20, "IfcProductDefinitionShape", Representations=[rep])
        product = Entity(30, "IfcSlab")
        index = SemanticIndex()
        index.rep_owner[10] = owner; index.owner_product[20] = product
        for cid, identifier in enumerate(identifiers, 100):
            value = context(cid, identifier)
            index.contexts[cid] = value
            index.context_info[cid] = ContextInfo(cid, value.is_a(), identifier, "Model",
                                                   "MODEL_VIEW", 1, 3, True)
        return rep, product, index

    def test_equivalent_product_evidence_is_safe(self):
        rep, product, index = self.setup_index(["Body", "Axis"])
        index.matching_contexts[index.signature(rep, product)][100] = 4
        result = resolve_context(rep, index)
        self.assertEqual(result.status, Status.SAFE)
        self.assertEqual(result.context.id(), 100)

    def test_identifier_only_is_warning(self):
        rep, _, index = self.setup_index(["Custom", "Axis"], "Custom")
        result = resolve_context(rep, index)
        self.assertEqual(result.status, Status.WARNING)
        self.assertEqual(result.context.id(), 100)

    def test_supplied_clean_profile_upgrades_matching_slab_body(self):
        rep, _, index = self.setup_index(["Body", "Axis"])
        result = resolve_context(rep, index)
        self.assertEqual(result.status, Status.SAFE)
        self.assertTrue(any("supplied clean Revit samples" in item for item in result.evidence))

    def test_equal_matching_contexts_are_ambiguous(self):
        rep, _, index = self.setup_index(["Body", "Body"])
        self.assertEqual(resolve_context(rep, index).status, Status.AMBIGUOUS)

    def test_no_matching_context_is_not_repairable(self):
        rep, _, index = self.setup_index(["Axis", "FootPrint"])
        self.assertEqual(resolve_context(rep, index).status, Status.NOT_REPAIRABLE)

    def test_matching_sibling_is_safe(self):
        rep, _, index = self.setup_index(["Body", "Axis"])
        sibling = Entity(12, "IfcShapeRepresentation", RepresentationIdentifier="Body",
                         RepresentationType="Brep", Items=[], ContextOfItems=index.contexts[100])
        index.rep_owner[10].Representations.append(sibling)
        result = resolve_context(rep, index)
        self.assertEqual(result.status, Status.SAFE)


if __name__ == "__main__":
    unittest.main()
