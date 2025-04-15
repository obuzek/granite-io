# SPDX-License-Identifier: Apache-2.0

"""
Parser which receives Granite model output and returns the constituents of the output.

The input to the parser is assumed to be as follows:

    response_text

    # Citations:
    citations_text

    # Hallucinations:
    hallucinations_text

The output from the parser returns a dictionary as follows:

    "citations": List of citations
    "docs": List of document references
    "hallucinations": List of hallucinations
    "response": Model response text without the above constituents

"""

# Standard
import copy
import logging
import re

# Third Party
from nltk import sent_tokenize  # pylint: disable=import-error

from granite_io.io.consts import (
    _GRANITE_3_3_CITE_END,
    _GRANITE_3_3_CITE_START,
    _GRANITE_3_3_CITATIONS_START,
    _GRANITE_3_3_HALLUCINATIONS_START,
)


def _find_substring_in_text(substring: str, text: str) -> list[dict[str, int]]:
    """
    Given two strings - substring and text - find and return all
    matches of substring within text. For each match return its begin and end index
    """
    span_matches = []

    matches_iter = re.finditer(re.escape(substring), text)
    for match in matches_iter:
        span_matches.append({"begin_idx": match.start(), "end_idx": match.end()})

    return span_matches


def _parse_hallucinations_text(hallucinations_text: str) -> list[dict]:
    """
    Given the hallucinations text output by model under the "# Hallucinations:"
    section, extract the hallucinations info as an array of the form:

    [
        {
            "hallucination_id": "Hallucination ID output by model",
            "risk": "Hallucination risk flag",
            "response_text": "Substring of response text for which
                                hallucination risk is computed"
        },
        ...
    ]
    """

    hallucinations = []

    # Find begin spans of all hallucinations
    matches_iter = re.finditer(
        "(\\d+)\\.\\s*Risk (low|high|unanswerable):",
        hallucinations_text,
    )
    matches = []
    for match in matches_iter:
        matches.append({"match_begin": match.start()})

    if len(matches) == 0:
        logging.error(
            "Failed to extract hallucination info."
            "Expected hallucination info but none found."
        )

    # For each hallucination, extract its components (hallucination ID,
    # risk, response text)
    for i in range(len(matches)):  # pylint: disable=consider-using-enumerate
        cur_match = matches[i]

        # Select text corresponding to hallucination (which is the text from the
        # beginning of the hallucination until the beginning of the next
        # hallucination or the end of the text; whichever comes first)
        if i + 1 < len(matches):
            next_match_begin = matches[i + 1]["match_begin"] - 1
        else:
            next_match_begin = len(hallucinations_text)
        hallucination_str = hallucinations_text[
            cur_match["match_begin"] : next_match_begin
        ]

        # Within the hallucination text, extract the citation components
        # (hallucination ID, risk, response text)
        # Use ?s flag to include newlines in match
        matches_iter = re.finditer(
            "(?s)(\\d+)\\.\\s*Risk (low|high|unanswerable): (.+)$",
            hallucination_str,
        )
        idx = 0
        for match in matches_iter:
            cur_hallucination = {
                "hallucination_id": match.group(1),
                "risk": match.group(2),
                "response_text": match.group(3),
            }
            hallucinations.append(cur_hallucination)

            idx += 1

        if idx == 0:
            logging.error("""Error in finding components of hallucination: \
                         Expected single RegEx match but found none.""")
        if idx > 1:
            logging.error("""Error in finding components of hallucination: \
                          Expected single RegEx match but found several.""")

    return hallucinations


def _add_hallucination_response_spans(
    hallucination_info: list[dict], response_text_without_citations: str
) -> list[dict]:
    """
    Given the response text (cleaned from citation tags) and a
    parsed hallucinations info of the form:

    [
        {
            "hallucination_id": "Hallucination ID output by model",
            "risk": "Hallucination risk flag",
            "response_text": "Substring of response text for which hallucination
                                risk is computed"
        },
        ...
    ]

    add to each hallucination element in the array the following attributes
    (the "response_text" replaces the attribute of the same name):

        "response_text": "The response text corresponding to the hallucination
                            element cleaned from citation tags"
        "response_begin": "The begin index of "response_text" within the response
                            text (without citation tags)"
        "response_end": "The end index of "response_text" within the response
                            text (without citation tags)"
    """

    augmented_hallucination_info = copy.deepcopy(hallucination_info)

    for hallucination in augmented_hallucination_info:
        hallucination_response_text_without_citations = (
            _remove_citations_from_response_text(hallucination["response_text"])
        )
        matches = _find_substring_in_text(
            hallucination_response_text_without_citations,
            response_text_without_citations,
        )
        if len(matches) == 0:
            logging.error("""Error in adding the response spans to hallucination: \
                          Hallucination text not found in response""")
            continue

        if len(matches) > 1:
            logging.warning("""Hallucination text found multiple times in \
                            response: Selecting first match""")
        hallucination["response_text"] = hallucination_response_text_without_citations
        hallucination["response_begin"] = matches[0]["begin_idx"]
        hallucination["response_end"] = matches[0]["end_idx"]

    return augmented_hallucination_info


def _parse_citations_text(citations_text: str) -> list[dict]:
    """
    Given the citations text output by model under the "# Citations:" section,
    extract the citation info as an array of the form:

    [
        {
            "citation_id": "Citation ID output by model",
            "doc_id": "ID of doc where the cited text is drawn from",
            "context_text": "The cited text from the context"
        },
        ...
    ]
    """

    citations = []

    # Find citations in the response
    pattern = r"(\d+):(.+)"
    matches_iter = re.finditer(pattern, citations_text)
    matches = []
    for match in matches_iter:
        matches.append({"match_begin": match.start()})

    if len(matches) == 0:
        logging.error(
            "Error in extracting citation info. Expected citations but found none."
        )
        return citations

    # For each citation, extract its components (citation ID, doc ID, context text)
    for i in range(len(matches)):  # pylint: disable=consider-using-enumerate
        cur_match = matches[i]

        # Select text corresponding to citation (which is the text from the beginning
        # of the citation until the beginning of the next citation or the end of the
        # text; whichever comes first)
        if i + 1 < len(matches):
            next_match_begin = matches[i + 1]["match_begin"] - 1
        else:
            next_match_begin = len(citations_text)
        citation_str = citations_text[cur_match["match_begin"] : next_match_begin]

        # Within the citation text, extract the citation components
        # (citation ID, doc ID, context text)
        # Use ?s flag to include newlines in match
        pattern = r"(\d+):(.+)"
        matches_iter = re.finditer(
            pattern,
            citation_str,
        )
        idx = 0
        for match in matches_iter:
            context_text = match.group(2).strip().strip('"')

            cur_citation = {
                "citation_id": str(idx),
                "doc_id": match.group(1),
                "context_text": context_text,
            }
            citations.append(cur_citation)

            idx += 1

        if idx == 0:
            logging.error("Error in finding components of citation: Expected single RegEx match but found none.")
        if idx > 1:
            logging.error("Error in finding components of citation: Expected single RegEx match but found several.")

    return citations


def _add_citation_context_spans(
    citation_info: list[dict], docs: list[dict]
) -> list[dict]:
    """
    Given a set of docs and an array of citations of the form:

    [
        {
            "citation_id": "Citation ID output by model",
            "doc_id": "ID of doc where the cited text is drawn from",
            "context_text": "The cited text from the context"
        },
        ...
    ]

    add to each citation in the array the following two attributes:

        "context_begin": "The begin index of "context_text" within document with
                            ID doc_id"
        "context_end": "The end index of "context_text" within document with ID doc_id"
    """
    augmented_citation_info = copy.deepcopy(citation_info)
    docs_by_cit_doc_id = _create_dict(
        docs, citation_attrib="citation_id", document_attrib="doc_id"
    )
    for citation in augmented_citation_info:
        # Init values in event of error in processing
        citation["context_begin"] = 0
        citation["context_end"] = 0
        try:
            dict_id = str(citation["citation_id"]) + "-" + citation["doc_id"]
            doc = docs_by_cit_doc_id[dict_id]
        except KeyError:
            logging.error(
                f"Document with id: {dict_id} not found "
                f"when adding citation context spans."
            )
            continue

        matches = _find_substring_in_text(citation["context_text"], doc["text"])
        if len(matches) == 0:
            logging.error("""Error in adding the context spans to citation: \
                            Cited text not found in corresponding document""")
            continue

        if len(matches) > 1:
            logging.warning("""Cited text found multiple times in corresponding \
                            document: Selecting first match""")
        citation["context_begin"] = matches[0]["begin_idx"]
        citation["context_end"] = matches[0]["end_idx"]

    return augmented_citation_info


def _add_citation_response_spans(
    citation_info: list[dict],
    response_text_with_citations: str,
    response_text_without_citations: str,
) -> list[dict]:
    """
    Given the response text in two forms (the original with citation tags and
    the processed without) and an array of parsed citations of the form:

    [
        {
            "citation_id": "Citation ID output by model",
            "doc_id": "ID of doc where the cited text is drawn from",
            "context_text": "The cited text from the context",
            "context_begin": "The begin index of "context_text" within document with
                                ID doc_id" (Optional)
            "context_end": "The end index of "context_text" within document with
                                ID doc_id" (Optional)
        },
        ...
    ]

    add to each citation in the array the following two attributes:
        "response_text": "The substring of the response for which the citation is
                            provided"
        "response_begin": "The begin index of "response_text" within the response text"
        "response_end": "The end index of "response_text" within the response text"
    """

    augmented_citation_info = copy.deepcopy(citation_info)

    # Split response into sentences
    response_sentences = sent_tokenize(response_text_with_citations)

    # Create dictionary of the response sentence (cleaned from citations) corresponding
    # to each citation ID
    response_sents_by_citation_id = {}
    citation_idx = 0
    for sent_idx, sent in enumerate(response_sentences):
        pattern = f'{re.escape(_GRANITE_3_3_CITE_START)}{{"document_id": "(\d+)"}}{re.escape(_GRANITE_3_3_CITE_END)}'
        matches_iter = re.finditer(pattern, sent)
        for match in matches_iter:
            citation_id = str(citation_idx)
            if citation_idx > len(augmented_citation_info) - 1:
                augmented_citation_info.append({})  # Too many, add extra
            augmented_citation_info[citation_idx]["citation_id"] = citation_id
            augmented_citation_info[citation_idx]["document_id"] = match.group(1)
            citation_idx = citation_idx + 1
            if citation_id not in response_sents_by_citation_id:
                sent_without_citations = _remove_citations_from_response_text(sent)
                # Fixes for sentence splitting issue: Associate citation with previous
                # sentence if either of the following holds:
                # - The citation ID appears at the beginning of a sentence
                # - The found sentence is empty after removing citations
                if (match.start() == 0) or (len(sent_without_citations) == 0):
                    if sent_idx > 0:
                        sent_without_citations = _remove_citations_from_response_text(
                            response_sentences[sent_idx - 1]
                        )
                    else:
                        logging.error("Error in extracting the response sentence of a citation: Found empty sentence")
                        response_sents_by_citation_id[citation_id] = ""
                        continue
                response_sents_by_citation_id[citation_id] = sent_without_citations
            else:
                logging.error("""Error in extracting the response sentence of a \
                                citation: Citation ID appears in more than one \
                                response sentences""")
                continue

    # For each citation bring the response sentence to which it refers and its
    # begin/end spans
    for i, citation in enumerate(augmented_citation_info):
        response_text = response_sents_by_citation_id.get(str(i), "")
        index = response_text_without_citations.find(response_text)
        if index < 0:
            logging.warning("Error in extracting the response sentence of a citation: Unexpected error.")
            continue

        citation["response_text"] = response_text
        citation["response_begin"] = index
        citation["response_end"] = index + len(response_text_without_citations)

    return augmented_citation_info


def _get_docs_from_citations(docs: str) -> list[dict]:
    """
    Given a multi-line string with document information per line, extract
    and add to dictionary list with "doc_id" and "text" fields

    Document line format:
    1: "<text>"
    2: "<text>"
    <|something to ignore|>
    """
    doc_dicts = []
    if not docs or docs.isspace():
        return doc_dicts
    for i, line in enumerate(docs.splitlines()):
        if not line or line.isspace():
            continue
        line_split = line.split(":", maxsplit=1)
        if len(line_split) <= 1:
            logging.debug(f"""Unable to retrieve doc text from: {line}""")
            continue
        doc_id = line_split[0].strip()
        if not doc_id.isdigit():
            logging.error(f"""Unable to retrieve doc id from: {line}""")
            continue
        text = line_split[1].strip().strip('"')

        # Using line index as citation_id
        doc_dicts.append({"citation_id": str(i), "doc_id": doc_id, "text": text})
    return doc_dicts


def _create_dict(input_array: object, **key_attrib_names: str) -> dict:
    """
    Given an array of dicts and the name of attribute(s) within the array, return a
    dict containing the contents of the array indexed by the given attribute(s)
    """
    new_dict = {}

    for item in input_array:
        new_dict_key_val: str = ""
        key_attribs_len = len(key_attrib_names)
        # Key for dictionary will be a combinations of attribute(s)
        # the dictionary that we are trying to index
        for key_attrib in key_attrib_names.values():
            new_dict_key_val += str(item[key_attrib])
            key_attribs_len -= 1
            if key_attribs_len > 0:
                new_dict_key_val += "-"

        if new_dict_key_val in new_dict:
            logging.error(
                f"Found duplicate item while creating dictionary: "
                f"{new_dict[new_dict_key_val]}"
            )

        new_dict[new_dict_key_val] = item

    return new_dict


def _remove_citations_from_response_text(response_text: str) -> str:
    """
    Given a response text (potentially containing inline <co>...</co> tags),
    return the response text cleaned up from the <co>...</co> tags
    """

    # TODO:  Need a better way to turn on and then remove special tokens
    sop = "<|start_of_plugin|>"
    ret = response_text.replace(sop, "")
    eop = "<|end_of_plugin|>"
    ret = ret.replace(eop, "")
    pattern = f'{re.escape(_GRANITE_3_3_CITE_START)}{{"document_id": "\\d+"}}{re.escape(_GRANITE_3_3_CITE_END)}'
    return re.sub(pattern, "", ret).strip()


def _validate_response(response_text: str, citation_info: object):
    start = re.escape(_GRANITE_3_3_CITE_START)
    end = re.escape(_GRANITE_3_3_CITE_END)
    pattern = f"{start}(?:(?!({start}|{end})).)*{start}(?:(?!({start}|{end})).)*{end}"
    if re.search(
        pattern, response_text
    ):
        logging.warning(f"Response contains nested citations: {response_text}")

    opening_tag_count = response_text.count(_GRANITE_3_3_CITE_START)
    closing_tag_count = response_text.count(_GRANITE_3_3_CITE_END)

    if opening_tag_count != closing_tag_count:
        logging.warning(f"""Response contains different number of cite start and end symbols: {response_text}""")

    if opening_tag_count != len(citation_info):
        logging.warning(f"Response contains different number of citations than those listed': {response_text}")


def _split_model_output_into_parts(model_output: str) -> tuple[str, str, str]:
    """
    Divide the model output into its constituent parts: response_text, citations_text,
    and hallucinations_text.

    This assumes that the model output is of the following form:

    response_text
    # Citations
    citations_text
    # Hallucinations
    hallucinations_text

    where:
    - "TODO: # Citations" and "# Hallucinations> are literals, and
    - response_text, citations_text, hallucinations_text are variables corresponding
        the parts of the output

    Note:
    - The citations and hallucinations sections are both optional
    """
    citations_text = ""
    hallucinations_text = ""

    if _GRANITE_3_3_HALLUCINATIONS_START in model_output and _GRANITE_3_3_CITATIONS_START not in model_output:
        response_text, hallucinations_text = model_output.split(_GRANITE_3_3_HALLUCINATIONS_START)
    elif _GRANITE_3_3_CITATIONS_START in model_output and _GRANITE_3_3_HALLUCINATIONS_START not in model_output:
        response_text, citations_text = model_output.split(_GRANITE_3_3_CITATIONS_START)
    elif _GRANITE_3_3_CITATIONS_START in model_output and _GRANITE_3_3_HALLUCINATIONS_START in model_output:
        pre_citation_split, post_citation_split = model_output.split(_GRANITE_3_3_CITATIONS_START)
        if _GRANITE_3_3_HALLUCINATIONS_START in pre_citation_split:
            response_text, hallucinations_text = pre_citation_split.split(
                _GRANITE_3_3_HALLUCINATIONS_START
            )
            citations_text = post_citation_split
        else:
            citations_text, hallucinations_text = post_citation_split.split(
                _GRANITE_3_3_HALLUCINATIONS_START
            )
            response_text = pre_citation_split
    else:
        response_text = model_output

    # TODO:  Need a better way to turn on and then remove special tokens
    sop = "<|start_of_plugin|>"
    eop = "<|end_of_plugin|>"
    response_text = response_text.replace(sop, "").replace(eop, "")
    citations_text = citations_text.replace(sop, "").replace(eop, "")
    hallucinations_text = hallucinations_text.replace(sop, "").replace(eop, "")
    return response_text.strip(), citations_text.strip(), hallucinations_text.strip()


def _validate_spans_in_parser_output(parsed_task: object):
    """
    Validate that the hallucination and citation spans correspond to
    the model response
    """
    for hallucination in (
        parsed_task["hallucinations"] if parsed_task["hallucinations"] else []
    ):
        if "response_end" in hallucination and (
            hallucination["response_text"]
            != parsed_task["response"][
                hallucination["response_begin"] : hallucination["response_end"]
            ]
        ):
            logging.error("Unexpected error in generated hallucination response span")
    for citation in parsed_task["citations"] if parsed_task["citations"] else []:
        docs_by_cit_doc_id = _create_dict(
            parsed_task["docs"], citation_attrib="citation_id", document_attrib="doc_id"
        )
        try:
            dict_id = citation["citation_id"] + "-" + citation["doc_id"]
            doc = docs_by_cit_doc_id[dict_id]
        except KeyError:
            logging.error(
                f"Document with id: {dict_id} not found "
                f"when validation citation context spans."
            )
            continue
        if (
            citation["context_text"]
            != doc["text"][citation["context_begin"] : citation["context_end"]]
        ):
            logging.error("Unexpected error in generated citation context span")


def _update_docs_text_with_input_docs(
    docs_from_input: list[object], docs_from_citation: list[dict[str, str]]
) -> list[dict[str, str]]:
    """
    The documents passed in the chat completion call is the source of the documents
    used for the model output. The document text output by the model may not show
    the full context. Therefore, to have the full context, need to retrieve from the
    input passed to chat completion call, all documents and update the text in the
    citation documents to be aligned before finding the context spans.
    """

    augmented_docs_from_citation = copy.deepcopy(docs_from_citation)
    for citation_doc in augmented_docs_from_citation:
        for input_doc in docs_from_input:
            if citation_doc["text"].strip() in input_doc.text.strip():
                citation_doc["text"] = input_doc.text.strip()

    return augmented_docs_from_citation


def parse_model_output(
    model_output: str, docs_from_input: list[object]
) -> list[str | dict]:
    """
    Parse the constituents of the output (response) of a model into
    a format where they can be accessed individually

    Args:
        model_output: The response from model request
    Returns:
        Parsed part of the model output as follows:
            "docs": Document references
            "response": Model response without citations,
            "citations": Citations,
            "hallucinations": Hallucinations
    }
    """

    # Split model output into its parts: response, citation, and hallucination section
    response_text, citations_text, hallucinations_text = _split_model_output_into_parts(
        model_output
    )

    # Get documents from citations
    docs_from_citation = _get_docs_from_citations(citations_text)

    # Update 'docs_from_citation' with text from docs used as input to model prompt
    # as they are the full source of text. The full text is required to retrieve
    # context spans.
    docs = _update_docs_text_with_input_docs(docs_from_input, docs_from_citation)

    # Parsed response text
    response_text_without_citations = _remove_citations_from_response_text(
        response_text
    ).strip()

    # Parse hallucinations text
    if len(hallucinations_text) > 0:
        hallucination_info = _parse_hallucinations_text(hallucinations_text)
        augmented_hallucination_info = _add_hallucination_response_spans(
            hallucination_info, response_text_without_citations
        )
    else:
        augmented_hallucination_info = []
    logging.info(f"Parsed hallucination info:\n\n{augmented_hallucination_info}\n")

    # Parse citations text
    if len(citations_text) > 0:
        citation_info = _parse_citations_text(citations_text)
        citation_info_with_context_spans = _add_citation_context_spans(
            citation_info, docs
        )
        citation_info_with_context_response_spans = _add_citation_response_spans(
            citation_info_with_context_spans,
            response_text,
            response_text_without_citations,
        )
        _validate_response(response_text, citation_info)
    else:
        citation_info_with_context_response_spans = []
    logging.info(f"""Parsed citation info:\n\n\
                 {citation_info_with_context_response_spans}\n""")

    # Join all objects into single output
    result = {
        "docs": docs if docs else None,
        "response": response_text_without_citations,
        "citations": (
            citation_info_with_context_response_spans
            if citation_info_with_context_response_spans
            else None
        ),
        "hallucinations": (
            augmented_hallucination_info if augmented_hallucination_info else None
        ),
    }
    logging.info(f"Combined parser output:\n\n{result}\n")

    # Validate spans in parser output by checking if the citation/response text
    # matches the begin/end spans
    _validate_spans_in_parser_output(result)

    return result
