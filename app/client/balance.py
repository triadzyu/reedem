from datetime import timezone, datetime
import json
import time
import uuid

import requests
from app.client.encrypt import API_KEY, build_encrypted_field, decrypt_xdata, encryptsign_xdata, get_x_signature_payment, java_like_timestamp
from app.client.engsel import BASE_API_URL, UA, intercept_page, send_api_request
from app.type_dict import PaymentItem

def settlement_balance(
    api_key: str,
    tokens: dict,
    items: list[PaymentItem],
    payment_for: str,
    ask_overwrite: bool,
    overwrite_amount: int = -1,
    token_confirmation_idx: int = 0,
    amount_idx: int = -1,
):
    # Sanity check
    if overwrite_amount == -1 and not ask_overwrite:
        print("Either ask_overwrite must be True or overwrite_amount must be set.")
        return None

    token_confirmation = items[token_confirmation_idx]["token_confirmation"]
    payment_targets = ""
    for item in items:
        if payment_targets != "":
            payment_targets += ";"
        payment_targets += item["item_code"]

    amount_int = 0
    
    # Determine amount to use
    if overwrite_amount != -1:
        amount_int = overwrite_amount
    elif amount_idx == -1:
        amount_int = items[amount_idx]["item_price"]

    # If Overwrite
    if ask_overwrite:
        print(f"Total amount is {amount_int}.\nEnter new amount if you need to overwrite.")
        amount_str = input("Press enter to ignore & use default amount: ")
        if amount_str != "":
            try:
                amount_int = int(amount_str)
            except ValueError:
                print("Invalid overwrite input, using original price.")
                # return None
    intercept_page(api_key, tokens, items[0]["item_code"], False)
    
    # Get payment methods
    payment_path = "payments/api/v8/payment-methods-option"
    payment_payload = {
        "payment_type": "PURCHASE",
        "is_enterprise": False,
        "payment_target": items[0]["item_code"],
        "lang": "en",
        "is_referral": False,
        "token_confirmation": token_confirmation
    }
    
    print("Getting payment methods...")
    payment_res = send_api_request(api_key, payment_path, payment_payload, tokens["id_token"], "POST")
    if payment_res["status"] != "SUCCESS":
        print("Failed to fetch payment methods.")
        print(f"Error: {payment_res}")
        return payment_res
    
    token_payment = payment_res["data"]["token_payment"]
    ts_to_sign = payment_res["data"]["timestamp"]
    
    # Settlement request
    path = "payments/api/v8/settlement-multipayment"
    settlement_payload = {
        "total_discount": 0,
        "is_enterprise": False,
        "payment_token": "",
        "token_payment": token_payment,
        "activated_autobuy_code": "",
        "cc_payment_type": "",
        "is_myxl_wallet": False,
        "pin": "",
        "ewallet_promo_id": "",
        "members": [],
        "total_fee": 0,
        "fingerprint": "",
        "autobuy_threshold_setting": {
            "label": "",
            "type": "",
            "value": 0
        },
        "is_use_point": False,
        "lang": "en",
        "payment_method": "BALANCE",
        "timestamp": int(time.time()),
        "points_gained": 0,
        "can_trigger_rating": False,
        "akrab_members": [],
        "akrab_parent_alias": "",
        "referral_unique_code": "",
        "coupon": "",
        "payment_for": payment_for,
        "with_upsell": False,
        "topup_number": "",
        "stage_token": "",
        "authentication_id": "",
        "encrypted_payment_token": build_encrypted_field(urlsafe_b64=True),
        "token": "",
        "token_confirmation": "",
        "access_token": tokens["access_token"],
        "wallet_number": "",
        "encrypted_authentication_id": build_encrypted_field(urlsafe_b64=True),
        "additional_data": {
            "original_price": items[-1]["item_price"],
            "is_spend_limit_temporary": False,
            "migration_type": "",
            "akrab_m2m_group_id": "false",
            "spend_limit_amount": 0,
            "is_spend_limit": False,
            "mission_id": "",
            "tax": 0,
            "quota_bonus": 0,
            "cashtag": "",
            "is_family_plan": False,
            "combo_details": [],
            "is_switch_plan": False,
            "discount_recurring": 0,
            "is_akrab_m2m": False,
            "balance_type": "PREPAID_BALANCE",
            "has_bonus": False,
            "discount_promo": 0
        },
        "total_amount": amount_int,
        "is_using_autobuy": False,
        "items": items,
    }
    
    encrypted_payload = encryptsign_xdata(
        api_key=api_key,
        method="POST",
        path=path,
        id_token=tokens["id_token"],
        payload=settlement_payload
    )
    
    xtime = int(encrypted_payload["encrypted_body"]["xtime"])
    sig_time_sec = (xtime // 1000)
    x_requested_at = datetime.fromtimestamp(sig_time_sec, tz=timezone.utc).astimezone()
    settlement_payload["timestamp"] = ts_to_sign
    
    body = encrypted_payload["encrypted_body"]
    x_sig = get_x_signature_payment(
                api_key,
                tokens["access_token"],
                ts_to_sign,
                payment_targets,
                token_payment,
                "BALANCE",
                payment_for,
                path
            )
    
    headers = {
        "host": BASE_API_URL.replace("https://", ""),
        "content-type": "application/json; charset=utf-8",
        "user-agent": UA,
        "x-api-key": API_KEY,
        "authorization": f"Bearer {tokens['id_token']}",
        "x-hv": "v3",
        "x-signature-time": str(sig_time_sec),
        "x-signature": x_sig,
        "x-request-id": str(uuid.uuid4()),
        "x-request-at": java_like_timestamp(x_requested_at),
        "x-version-app": "8.8.0",
    }
    
    url = f"{BASE_API_URL}/{path}"
    print("Sending settlement request...")
    resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
    
    try:
        decrypted_body = decrypt_xdata(api_key, json.loads(resp.text))
        if decrypted_body["status"] != "SUCCESS":
            print("Failed to initiate settlement.")
            print(f"Error: {decrypted_body}")
            return decrypted_body
        
        print(f"Purchase result:\n{json.dumps(decrypted_body, indent=2)}")
        
        return decrypted_body
    except Exception as e:
        print("[decrypt err]", e)
        return resp.text