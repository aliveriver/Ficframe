from ficframe.models import CharacterCard
from types import SimpleNamespace

from ficframe.prompt_bank import local_prompt_bank_values, merge_identity_prompt, merge_negative_prompt, review_reference_visual_prompt_bank


def test_local_prompt_bank_prefers_vlm_identity_and_keeps_negative_separate():
    card = CharacterCard(
        name="星源",
        prompt_en="lore text that should not override reference image",
        reference_visuals=[
            {
                "identity_prompt": "very long dark blue/black hair in a high ponytail, bright blue eyes, pale skin, dark blue tactical tunic, white high-collared shirt, utility belt, black leggings, tall dark boots.",
                "negative_identity_prompt": "short hair, red hair, blonde hair, green eyes, wrong outfit, invented accessories",
                "appearance_states": [
                    {
                        "label": "default",
                        "trigger": "Use unless story explicitly changes visible appearance.",
                        "prompt": "Default state: very long dark blue/black hair in a high ponytail, bright blue eyes, dark blue tactical tunic, utility belt, black leggings, tall dark boots.",
                        "scene_ids": [],
                    }
                ],
                "stable_visual_traits": ["very long dark blue/black hair in a high ponytail", "bright blue eyes", "pale skin"],
                "outfit_traits": ["dark blue tactical tunic", "utility belt", "black leggings"],
            }
        ],
    )

    values = local_prompt_bank_values(card)

    assert values["identity_prompt"].startswith("very long dark blue/black hair")
    assert "lore text" not in values["identity_prompt"]
    assert values["appearance_states"][0]["prompt"].startswith("Default state:")
    assert "wrong outfit" in values["negative_identity_prompt"]
    assert "hair:" not in values["negative_identity_prompt"].lower()


def test_merge_functions_preserve_baseline_vlm_fields():
    baseline = {
        "identity_prompt": "canonical identity",
        "vlm_identity_prompt": "canonical identity",
        "negative_identity_prompt": "wrong hair, wrong outfit",
    }

    assert merge_identity_prompt("LLM refinement that should be ignored", baseline) == "canonical identity"
    assert merge_negative_prompt("LLM refinement that should be ignored", baseline) == "wrong hair, wrong outfit"


def test_appearance_states_reject_nonvisual_character_arc():
    card = CharacterCard(
        name="星极",
        prompt_en="曾经相信星辰能指明未来，却在矿石病、亲情与权威压迫中被迫重新理解命运。",
        visual_traits=["long dark blue hair, blue eyes, white blouse, dark pleated skirt"],
        variable_states={
            "default": "曾经相信星辰能指明未来，却在矿石病、亲情与权威压迫中被迫重新理解命运，最终相信自己和妹妹的力量。"
        },
        appearance_states=[
            {
                "label": "default",
                "trigger": "Use unless the story explicitly states a visible appearance change.",
                "prompt": "曾经相信星辰能指明未来，却在矿石病、亲情与权威压迫中被迫重新理解命运，最终相信自己和妹妹的力量。",
                "scene_ids": [],
            }
        ],
    )

    values = local_prompt_bank_values(card)

    assert values["appearance_states"][0]["prompt"] == "long dark blue hair, blue eyes, white blouse, dark pleated skirt"


def test_review_reference_visual_prompt_bank_uses_separate_llm_reviews():
    class FakeProvider:
        config = SimpleNamespace(llm=SimpleNamespace(api_key="test"))

        def __init__(self):
            self.purposes = []

        def text(self, system, user, purpose=""):
            self.purposes.append(purpose)
            if purpose.endswith(":identity"):
                return '{"identity_prompt":"clean dark blue ponytail, blue eyes, tactical outfit"}'
            if purpose.endswith(":negative"):
                return '{"negative_identity_prompt":"short hair, green eyes, wrong outfit"}'
            if purpose.endswith(":states"):
                return '{"appearance_states":[{"label":"default","trigger":"Use unless story explicitly changes visible appearance.","prompt":"clean dark blue ponytail, blue eyes, tactical outfit","scene_ids":[]}]}'
            raise AssertionError(purpose)

    provider = FakeProvider()
    data = {
        "identity_prompt": "Identity Prompt: This needs to be good. Hair: dark blue.",
        "negative_identity_prompt": "wrong hair, wrong outfit",
    }

    reviewed = review_reference_visual_prompt_bank(CharacterCard(name="A"), data, provider, purpose="review")

    assert reviewed["identity_prompt"] == "clean dark blue ponytail, blue eyes, tactical outfit"
    assert reviewed["negative_identity_prompt"] == "short hair, green eyes, wrong outfit"
    assert reviewed["appearance_states"][0]["prompt"] == "clean dark blue ponytail, blue eyes, tactical outfit"
    assert reviewed["llm_reviewed"] is True
    assert provider.purposes == ["review:identity", "review:negative", "review:states"]
