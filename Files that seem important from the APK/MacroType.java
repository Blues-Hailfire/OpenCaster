package com.wbdl.wand.message;

import kotlin.Metadata;

@Metadata(d1 = {"\u0000\u0012\n\u0002\u0018\u0002\n\u0002\u0010\u0010\n\u0000\n\u0002\u0010\u000e\n\u0002\b\u000e\b\u0001\u0018\u00002\b\u0012\u0004\u0012\u00020\u00000\u0001B\u000f\b\u0002\u0012\u0006\u0010\u0002\u001a\u00020\u0003¢\u0006\u0002\u0010\u0004R\u0011\u0010\u0002\u001a\u00020\u0003¢\u0006\b\n\u0000\u001a\u0004\b\u0005\u0010\u0006j\u0002\b\u0007j\u0002\b\bj\u0002\b\tj\u0002\b\nj\u0002\b\u000bj\u0002\b\fj\u0002\b\rj\u0002\b\u000ej\u0002\b\u000fj\u0002\b\u0010¨\u0006\u0011"}, d2 = {"Lcom/wbdl/wand/message/MacroType;", "", "id", "", "(Ljava/lang/String;ILjava/lang/String;)V", "getId", "()Ljava/lang/String;", "PAIRING", "PAIRING_CONFIRMATION", "OC_WAND_WAVE1", "OC_WAND_WAVE2", "OC_WAND_WAVE3", "CONFIG_WAND", "READY_TO_CAST", "READY_TO_CAST_NO_HAPTIC", "GENERIC_ERROR", "CLEAR_LEDS", "wand_release"}, k = 1, mv = {1, 7, 1}, xi = 48)
/* compiled from: MacroType.kt */
public enum MacroType {
    PAIRING("pairing"),
    PAIRING_CONFIRMATION("pairing_confirmation"),
    OC_WAND_WAVE1("oc_wave1"),
    OC_WAND_WAVE2("oc_wave2"),
    OC_WAND_WAVE3("oc_wave3"),
    CONFIG_WAND("config_wand"),
    READY_TO_CAST("ready_to_cast"),
    READY_TO_CAST_NO_HAPTIC("ready_to_cast_no_haptic"),
    GENERIC_ERROR("generic_error"),
    CLEAR_LEDS("clear_leds");
    
    private final String id;

    private MacroType(String str) {
        this.id = str;
    }

    public final String getId() {
        return this.id;
    }
}
