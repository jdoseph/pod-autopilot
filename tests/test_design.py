from src import design


def test_text_designs_route_to_ideogram():
    assert design.pick_tier({"text_on_design": "Fueled by Chaos"}) == "text"
    assert design.pick_tier({"text_on_design": None}) == "schnell"
    assert design.pick_tier({}) == "schnell"


def test_model_inputs_match_each_api():
    flux = design.model_input("schnell", "p")
    assert flux == {"prompt": "p", "aspect_ratio": "3:4", "output_format": "png"}
    ideo = design.model_input("text", "p", aspect="1:1")
    assert ideo["style_type"] == "Design"
    assert ideo["magic_prompt_option"] == "Off"
    assert ideo["aspect_ratio"] == "1:1"
    assert "output_format" not in ideo  # not an Ideogram parameter


def test_aspect_per_product_type():
    assert design.pick_aspect("t-shirt") == "3:4"
    assert design.pick_aspect("Tote") == "1:1"   # square areas need square art
    assert design.pick_aspect("mug") == "1:1"
    assert design.pick_aspect("unknown") == "3:4"
    assert set(design.ASPECT_RATIO.values()) <= set(design.ASPECT_VALUE)


def test_every_tier_has_model_and_cost():
    from src import budget
    for tier in design.MODEL_URLS:
        assert tier in budget.IMAGE_COST
