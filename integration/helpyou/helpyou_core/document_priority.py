"""SIA Operations Manual document-authority policy for Helpyou.

This module records the source hierarchy stated in SIA OM Volume A Rev 32,
section 12.1.1.1.  It deliberately does not invent a total order where the OM
places documents in the same group or merely identifies them as Volume B
components.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DocumentPriorityError(ValueError):
    """Raised when a document class cannot be resolved safely."""


class DocumentClass(str, Enum):
    CERTIFICATE_OF_AIRWORTHINESS = "certificate_of_airworthiness"
    ANO_ANR = "ano_anr"
    AFM = "afm"
    INTAM = "intam"
    FSI = "fsi"
    MEL = "mel"
    OM_VOL_A = "om_vol_a"
    FCOM = "fcom"
    JEPPESEN_REFERENCE = "jeppesen_reference"
    SQNP = "sqnp"
    SQSP = "sqsp"
    SEP = "sep"
    FCTM = "fctm"
    TECHNICAL_BULLETIN = "technical_bulletin"
    AIRPORT_BRIEFING = "airport_briefing"
    CIRCULAR = "circular"
    CREW_ADMINISTRATION = "crew_administration"
    FLIGHT_SECURITY = "flight_security"
    QRH = "qrh"
    CDL = "cdl"
    SQI = "sqi"
    WEIGHT_AND_BALANCE = "weight_and_balance"
    FUELING_INSTRUCTIONS = "fueling_instructions"
    TRAINING_SYNTHESIS = "training_synthesis"
    COGNITIVE_FOUNDATION = "cognitive_foundation"
    PILOT_REPORT = "pilot_report"


class AuthorityBand(str, Enum):
    MANDATORY_AIRWORTHINESS = "mandatory_airworthiness"
    EXPLICIT_OM_PRIORITY = "explicit_om_priority"
    LINKED_VOLUME_B_COMPONENT = "linked_volume_b_component"
    SUPPORTING_ONLY = "supporting_only"
    NON_AUTHORITATIVE = "non_authoritative"


class PrecedenceRelation(str, Enum):
    A_HIGHER = "a_higher"
    B_HIGHER = "b_higher"
    SAME_OM_LEVEL = "same_om_level"
    COMBINED_COMPLIANCE_REQUIRED = "combined_compliance_required"
    SCOPE_RECONCILIATION_REQUIRED = "scope_reconciliation_required"


@dataclass(frozen=True)
class DocumentAuthority:
    document_class: DocumentClass
    band: AuthorityBand
    priority_rank: int | None
    primary_on_installed_efb: bool = False
    notes: tuple[str, ...] = ()


# OM 12.1.1.1 para (5): descending order of priority and authority.
_EXPLICIT_PRIORITY: dict[DocumentClass, int] = {
    DocumentClass.INTAM: 1,
    DocumentClass.FSI: 2,
    DocumentClass.MEL: 3,
    DocumentClass.OM_VOL_A: 4,
    DocumentClass.FCOM: 4,
    DocumentClass.JEPPESEN_REFERENCE: 4,
    DocumentClass.SQNP: 4,
    DocumentClass.SQSP: 4,
    DocumentClass.SEP: 5,
    DocumentClass.FCTM: 6,
    DocumentClass.TECHNICAL_BULLETIN: 6,
    DocumentClass.AIRPORT_BRIEFING: 6,
    DocumentClass.CIRCULAR: 6,
    DocumentClass.CREW_ADMINISTRATION: 7,
    DocumentClass.FLIGHT_SECURITY: 7,
}

_MANDATORY = {
    DocumentClass.CERTIFICATE_OF_AIRWORTHINESS,
    DocumentClass.ANO_ANR,
    DocumentClass.AFM,
}

# OM 1.1 identifies these as A350 Volume B component documents but OM 12.1.1.1
# does not assign each of them a separate rank in the descending list.
_LINKED_UNRANKED = {
    DocumentClass.QRH,
    DocumentClass.CDL,
    DocumentClass.SQI,
    DocumentClass.WEIGHT_AND_BALANCE,
    DocumentClass.FUELING_INSTRUCTIONS,
}

_SUPPORTING = {
    DocumentClass.TRAINING_SYNTHESIS,
    DocumentClass.COGNITIVE_FOUNDATION,
}

_NON_AUTHORITATIVE = {DocumentClass.PILOT_REPORT}


OM_MORE_RESTRICTIVE_RULE_APPLIES = True
INSTALLED_EFB_PRIMARY_DOCUMENTS = {
    DocumentClass.AFM,
    DocumentClass.MEL,
    DocumentClass.CDL,
}


def authority_for(document_class: DocumentClass) -> DocumentAuthority:
    """Return the OM-grounded authority classification for one document class."""

    if document_class in _MANDATORY:
        return DocumentAuthority(
            document_class=document_class,
            band=AuthorityBand.MANDATORY_AIRWORTHINESS,
            priority_rank=None,
            primary_on_installed_efb=document_class in INSTALLED_EFB_PRIMARY_DOCUMENTS,
            notes=(
                "All applicable airworthiness and regulatory provisions must be complied with.",
                "A lower-authority document may impose a more restrictive requirement.",
            ),
        )
    if document_class in _EXPLICIT_PRIORITY:
        return DocumentAuthority(
            document_class=document_class,
            band=AuthorityBand.EXPLICIT_OM_PRIORITY,
            priority_rank=_EXPLICIT_PRIORITY[document_class],
            primary_on_installed_efb=document_class in INSTALLED_EFB_PRIMARY_DOCUMENTS,
            notes=(
                "Rank follows the descending sequence in SIA OM 12.1.1.1 para (5).",
            ),
        )
    if document_class in _LINKED_UNRANKED:
        return DocumentAuthority(
            document_class=document_class,
            band=AuthorityBand.LINKED_VOLUME_B_COMPONENT,
            priority_rank=None,
            primary_on_installed_efb=document_class in INSTALLED_EFB_PRIMARY_DOCUMENTS,
            notes=(
                "Linked to A350 Volume B, but no separate rank is inferred from the component list.",
                "Resolve by subject scope, document relationship, revision and explicit OM policy.",
            ),
        )
    if document_class in _SUPPORTING:
        return DocumentAuthority(
            document_class=document_class,
            band=AuthorityBand.SUPPORTING_ONLY,
            priority_rank=None,
            notes=("May support teaching or navigation, but not operational authority.",),
        )
    if document_class in _NON_AUTHORITATIVE:
        return DocumentAuthority(
            document_class=document_class,
            band=AuthorityBand.NON_AUTHORITATIVE,
            priority_rank=None,
            notes=("Must remain visibly segregated from authoritative evidence.",),
        )
    raise DocumentPriorityError(f"Unclassified document class: {document_class}")


def explicit_descending_sequence() -> tuple[tuple[int, tuple[DocumentClass, ...]], ...]:
    """Return the exact OM operational priority groups without inventing sub-priority."""

    return tuple(
        (
            rank,
            tuple(
                item
                for item, item_rank in _EXPLICIT_PRIORITY.items()
                if item_rank == rank
            ),
        )
        for rank in range(1, 8)
    )


def precedence_between(a: DocumentClass, b: DocumentClass) -> PrecedenceRelation:
    """Compare two classes while preserving OM scope and same-level ambiguity."""

    auth_a = authority_for(a)
    auth_b = authority_for(b)

    if (
        auth_a.band is AuthorityBand.MANDATORY_AIRWORTHINESS
        or auth_b.band is AuthorityBand.MANDATORY_AIRWORTHINESS
    ):
        return PrecedenceRelation.COMBINED_COMPLIANCE_REQUIRED

    if (
        auth_a.band is AuthorityBand.EXPLICIT_OM_PRIORITY
        and auth_b.band is AuthorityBand.EXPLICIT_OM_PRIORITY
    ):
        assert auth_a.priority_rank is not None
        assert auth_b.priority_rank is not None
        if auth_a.priority_rank < auth_b.priority_rank:
            return PrecedenceRelation.A_HIGHER
        if auth_b.priority_rank < auth_a.priority_rank:
            return PrecedenceRelation.B_HIGHER
        return PrecedenceRelation.SAME_OM_LEVEL

    return PrecedenceRelation.SCOPE_RECONCILIATION_REQUIRED


def latest_copy_rule() -> str:
    """Return the OM rule for differing iPad and installed-EFB revisions."""

    return (
        "Use the latest revision when document versions differ; on an installed EFB, "
        "the AFM, MEL and CDL copies are the primary operational references."
    )
