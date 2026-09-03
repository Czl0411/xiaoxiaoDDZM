from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_commission_house_is_one_visible_module_with_all_commands_and_order_admin():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert html.count('data-page="bounties"') == 1
    assert 'data-page="marketplace"' not in html
    assert "群友委托所" in html
    assert 'id="commissionServiceTable"' in html
    assert 'id="commissionOrderTable"' in html
    assert 'id="commissionLegacyMarket" class="hidden" hidden' in html
    assert 'id="commissionDemandModal"' in html
    assert 'id="commissionServiceModal"' in html

    command_ids = (
        "commissionRequestPublishCommands",
        "commissionServicePublishCommands",
        "commissionConfirmDraftCommands",
        "commissionCancelDraftCommands",
        "commissionRequestListCommands",
        "commissionServiceListCommands",
        "commissionRequestDetailCommands",
        "commissionServiceDetailCommands",
        "commissionRequestAcceptCommands",
        "commissionServiceAcceptCommands",
        "commissionMyPostsCommands",
        "commissionMyDemandsCommands",
        "commissionMyServicesCommands",
        "commissionMyOrdersCommands",
        "commissionOrderDetailCommands",
        "commissionOrderCompleteCommands",
        "commissionOrderConfirmCommands",
        "commissionOrderCancelCommands",
        "commissionOrderCancelApproveCommands",
        "commissionOrderCancelRejectCommands",
        "commissionCloseRequestCommands",
        "commissionCloseServiceCommands",
        "commissionServiceRestockCommands",
        "commissionServiceRenewCommands",
        "commissionHelpCommands",
    )
    for element_id in command_ids:
        assert f'id="{element_id}"' in html
        assert element_id in script

    assert 'api("/api/commission-house/overview")' in script
    assert 'window.adminCommissionOrder' in script
    assert 'window.openCommissionDemandEdit' in script
    assert 'window.openCommissionServiceEdit' in script


def test_separate_list_templates_explicitly_keep_the_nine_line_limit():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    style = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    assert "需求列表文案（机器人强制压缩为最多9行）" in html
    assert "服务列表文案（机器人强制压缩为最多9行）" in html
    assert 'id="commissionRequestListItemReply"' in html
    assert 'id="commissionServiceListItemReply"' in html
    assert "/查看需求2" in html and "/查看服务2" in html
    assert "[hidden], .hidden" in style
    assert 'class="three hidden" hidden' in html
    assert "服务是持续上架出售" in html
    assert 'id="commissionDemandAiSystemPrompt"' in html
    assert 'id="commissionServiceAiSystemPrompt"' in html
    assert 'id="commissionPromptHistory"' in html
    assert "人数、份数、数量都解释为库存" in html
