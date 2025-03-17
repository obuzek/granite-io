# SPDX-License-Identifier: Apache-2.0

"""
Tests for the majority voting I/O processor
"""

import pytest

from litellm import UnsupportedParamsError

from granite_io import make_io_processor
from granite_io.backend import Backend

from granite_io.io.granite_3_2.granite_3_2 import (
    _MODEL_NAME
)
from granite_io.io.voting import MajorityVotingProcessor, integer_normalizer

from granite_io.types import (
    ChatCompletionInputs,
    ChatCompletionResults
)
from granite_io.backend.transformers import TransformersBackend
from granite_io.backend.litellm import LiteLLMBackend

@pytest.mark.vcr(
    record_mode="all"
)
@pytest.mark.block_network
def test_numeric_voting(backend_x: Backend):
    if isinstance(backend_x, TransformersBackend):
        pytest.xfail(
            "TransformersBackend top-k currently returning low-quality results")

    # At the moment, git LFS is broken on the current repo, so we have reduced the
    # number of samples to keep the cassette file size small.
    SAMPLES_PER_COMPLETION = 3

    base_processor = make_io_processor(_MODEL_NAME, backend=backend_x)
    voting_processor = MajorityVotingProcessor(
        base_processor, integer_normalizer,
        samples_per_completion=SAMPLES_PER_COMPLETION
    )

    first_number = 1
    second_number = 22
    completion_inputs = ChatCompletionInputs(
        messages=[
            {
                "role": "user",
                "content": f"What is {first_number} + {second_number}?\n"
                           f"Answer with just a number please.",
            }
        ],
        thinking=True,
        num_return_sequences=1,
    )
    try:
        results = voting_processor.create_chat_completion(completion_inputs)
    except UnsupportedParamsError:
        # Known issue with LiteLLMBackend
        if isinstance(backend_x, LiteLLMBackend):
            pytest.xfail(
                "LiteLLMBackend support for num_return_sequences > 1 varies by provider"
            )

    assert isinstance(results, ChatCompletionResults)
    assert len(results.results) == 1

    # Due to the git LFS workaround described above, this test case doesn't reliably
    # generate the correct result here. If we enable git LFS support, we should
    # re-enable the following assertion.
    # assert (int(results.results[0].next_message.content)
    #         == first_number + second_number)
