from src import design


def test_text_designs_route_to_ideogram():
    assert design.pick_tier({"text_on_design": "Fueled by Chaos"}) == "text"
    assert design.pick_tier({"text_on_design": None}) == "schnell"
    assert design.pick_tier({}) == "schnell"


def test_model_inputs_match_each_api():
    flux = design.model_input("schnell", "p")
    assert flux == {"prompt": "p", "aspect_ratio": "3:4", "output_format": "png"}
    ideo = design.model_input("text", "p")
    assert ideo["style_type"] == "Design"
    assert ideo["magic_prompt_option"] == "Off"
    assert "output_format" not in ideo  # not an Ideogram parameter


def test_every_tier_has_model_and_cost():
    from src import budget
    for tier in design.MODEL_URLS:
        assert tier in budget.IMAGE_COST
