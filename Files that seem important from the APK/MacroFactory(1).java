package com.wbdl.wand.message;

import android.content.res.Resources;
import com.wbdl.bluetooth.ble.message.struct.version1.a;
import com.wbdl.bluetooth.ble.message.struct.version1.a0;
import com.wbdl.bluetooth.ble.message.struct.version1.b0;
import com.wbdl.bluetooth.ble.message.struct.version1.c0;
import com.wbdl.bluetooth.ble.message.struct.version1.d0;
import com.wbdl.bluetooth.ble.message.struct.version1.v;
import com.wbdl.bluetooth.ble.message.struct.version1.w;
import com.wbdl.bluetooth.ble.message.struct.version1.y;
import com.wbdl.bluetooth.ble.message.struct.version1.z;
import com.wbdl.network.elder.model.CommandWand;
import com.wbdl.network.elder.model.CommandWandbox;
import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.List;
import kotlin.Metadata;
import kotlin.collections.q;
import kotlin.collections.r;
import kotlin.jvm.internal.DefaultConstructorMarker;
import kotlin.jvm.internal.p;
import org.json.JSONObject;

@Metadata(bv = {}, d1 = {"\u0000t\n\u0002\u0018\u0002\n\u0002\u0010\u0000\n\u0002\u0010 \n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0010\b\n\u0002\b\u0002\n\u0002\u0018\u0002\n\u0002\b\u0004\n\u0002\u0018\u0002\n\u0002\u0018\u0002\n\u0002\b\u0002\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0010\u000e\n\u0000\n\u0002\u0010\u000b\n\u0002\b\u0007\n\u0002\u0018\u0002\n\u0002\b\b\u0018\u0000 22\u00020\u0001:\u00012B\u0017\u0012\u0006\u0010,\u001a\u00020+\u0012\u0006\u0010.\u001a\u00020\u0007¢\u0006\u0004\b0\u00101J\u001c\u0010\u0006\u001a\b\u0012\u0004\u0012\u00020\u00050\u00022\f\u0010\u0004\u001a\b\u0012\u0004\u0012\u00020\u00030\u0002H\u0002J\u0016\u0010\t\u001a\b\u0012\u0004\u0012\u00020\u00030\u00022\u0006\u0010\b\u001a\u00020\u0007H\u0002J\u001c\u0010\f\u001a\b\u0012\u0004\u0012\u00020\u00030\u00022\f\u0010\u000b\u001a\b\u0012\u0004\u0012\u00020\n0\u0002H\u0002J\u0012\u0010\u000e\u001a\u0004\u0018\u00010\u00032\u0006\u0010\r\u001a\u00020\nH\u0002J\u001c\u0010\t\u001a\b\u0012\u0004\u0012\u00020\u00030\u00022\f\u0010\u000b\u001a\b\u0012\u0004\u0012\u00020\u000f0\u0002H\u0002J\u0012\u0010\u000e\u001a\u0004\u0018\u00010\u00032\u0006\u0010\r\u001a\u00020\u000fH\u0002J\u0012\u0010\u0012\u001a\u0004\u0018\u00010\u00032\u0006\u0010\u0011\u001a\u00020\u0010H\u0002J\b\u0010\u0014\u001a\u00020\u0013H\u0002J\b\u0010\u0016\u001a\u00020\u0015H\u0002J\u0012\u0010\u0018\u001a\u0004\u0018\u00010\u00172\u0006\u0010\u0011\u001a\u00020\u0010H\u0002J\u0010\u0010\u0018\u001a\u00020\u00172\u0006\u0010\r\u001a\u00020\u000fH\u0002J\u0010\u0010\u0018\u001a\u00020\u00172\u0006\u0010\r\u001a\u00020\nH\u0002J\u0012\u0010\u001a\u001a\u0004\u0018\u00010\u00192\u0006\u0010\u0011\u001a\u00020\u0010H\u0002J\u0010\u0010\u001a\u001a\u00020\u00192\u0006\u0010\r\u001a\u00020\u000fH\u0002J\u0010\u0010\u001a\u001a\u00020\u00192\u0006\u0010\r\u001a\u00020\nH\u0002J\u0012\u0010\u001c\u001a\u0004\u0018\u00010\u001b2\u0006\u0010\u0011\u001a\u00020\u0010H\u0002J\u0010\u0010\u001c\u001a\u00020\u001b2\u0006\u0010\r\u001a\u00020\u000fH\u0002J\u0010\u0010\u001c\u001a\u00020\u001b2\u0006\u0010\r\u001a\u00020\nH\u0002J\b\u0010\u001e\u001a\u00020\u001dH\u0002J\u0012\u0010 \u001a\u0004\u0018\u00010\u001f2\u0006\u0010\u0011\u001a\u00020\u0010H\u0002J\u0010\u0010 \u001a\u00020\u001f2\u0006\u0010\r\u001a\u00020\u000fH\u0002J\u0010\u0010 \u001a\u00020\u001f2\u0006\u0010\r\u001a\u00020\nH\u0002J\u001e\u0010$\u001a\u00020#2\u0006\u0010\u0011\u001a\u00020\u00102\f\u0010\"\u001a\b\u0012\u0004\u0012\u00020!0\u0002H\u0002J\u000e\u0010%\u001a\b\u0012\u0004\u0012\u00020!0\u0002H\u0002J\u000e\u0010&\u001a\b\u0012\u0004\u0012\u00020!0\u0002H\u0002J\u000e\u0010'\u001a\b\u0012\u0004\u0012\u00020!0\u0002H\u0002J\u000e\u0010(\u001a\b\u0012\u0004\u0012\u00020!0\u0002H\u0002J\u001a\u0010)\u001a\b\u0012\u0004\u0012\u00020\u00050\u00022\f\u0010\u000b\u001a\b\u0012\u0004\u0012\u00020\n0\u0002J\u001a\u0010*\u001a\b\u0012\u0004\u0012\u00020\u00050\u00022\f\u0010\u000b\u001a\b\u0012\u0004\u0012\u00020\u000f0\u0002J\u0014\u0010\u0006\u001a\b\u0012\u0004\u0012\u00020\u00050\u00022\u0006\u0010\b\u001a\u00020\u0007R\u0016\u0010,\u001a\u00020+8\u0002@\u0002X\u000e¢\u0006\u0006\n\u0004\b,\u0010-R\u0016\u0010.\u001a\u00020\u00078\u0002@\u0002X\u000e¢\u0006\u0006\n\u0004\b.\u0010/¨\u00063"}, d2 = {"Lcom/wbdl/wand/message/MacroFactory;", "", "", "Lcom/wbdl/bluetooth/ble/message/struct/version1/a;", "list", "Lcom/wbdl/bluetooth/ble/message/struct/version1/v;", "buildMacroMessage", "", "resId", "buildMacroList", "Lcom/wbdl/network/elder/model/CommandWandbox;", "commands", "buildBoxMacroList", "command", "buildCommandFromObject", "Lcom/wbdl/network/elder/model/CommandWand;", "Lorg/json/JSONObject;", "jsonObject", "buildCommandFromMessage", "Lcom/wbdl/bluetooth/ble/message/struct/version1/d0;", "buildWaitBusy", "Lcom/wbdl/bluetooth/ble/message/struct/version1/z;", "buildClearLeds", "Lcom/wbdl/bluetooth/ble/message/struct/version1/w;", "buildDelay", "Lcom/wbdl/bluetooth/ble/message/struct/version1/y;", "buildBuzz", "Lcom/wbdl/bluetooth/ble/message/struct/version1/a0;", "buildChangeLed", "Lcom/wbdl/bluetooth/ble/message/struct/version1/b0;", "buildSetLoop", "Lcom/wbdl/bluetooth/ble/message/struct/version1/c0;", "buildSetLoops", "", "validation", "", "isValidMacro", "getDelayValidation", "getBuzzValidation", "getChangeLedValidation", "getSetLoopsValidation", "buildMacroFromBoxCommandList", "buildMacroFromCommandList", "Landroid/content/res/Resources;", "resources", "Landroid/content/res/Resources;", "mtu", "I", "<init>", "(Landroid/content/res/Resources;I)V", "Companion", "wand_release"}, k = 1, mv = {1, 7, 1})
/* compiled from: MacroFactory.kt */
public final class MacroFactory {
    public static final int BLE_MESSAGE_HEADER_SIZE = 5;
    public static final String BUZZ = "buzz";
    public static final String CHANGE_LED = "changeled";
    public static final String CLEAR_LEDS = "clearleds";
    public static final String COLOR = "color";
    public static final Companion Companion = new Companion((DefaultConstructorMarker) null);
    public static final String DELAY = "delay";
    public static final String DURATION = "duration";
    public static final String GROUP = "group";
    public static final String LOOPS = "loops";
    public static final int MAX_DURATION = 255;
    public static final int SECONDS = 1000;
    public static final String SET_LOOP = "loop";
    public static final String SET_LOOPS = "setloops";
    public static final String WAIT_BUSY = "waitbusy";
    private int mtu;
    private Resources resources;

    @Metadata(d1 = {"\u0000 \n\u0002\u0018\u0002\n\u0002\u0010\u0000\n\u0002\b\u0002\n\u0002\u0010\b\n\u0000\n\u0002\u0010\u000e\n\u0002\b\u000e\n\u0002\u0010\u0006\n\u0000\b\u0003\u0018\u00002\u00020\u0001B\u0007\b\u0002¢\u0006\u0002\u0010\u0002J\u0010\u0010\u0013\u001a\u00020\u00042\u0006\u0010\u0014\u001a\u00020\u0015H\u0002R\u000e\u0010\u0003\u001a\u00020\u0004XT¢\u0006\u0002\n\u0000R\u000e\u0010\u0005\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\u0007\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\b\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\t\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\n\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\u000b\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\f\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\r\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\u000e\u001a\u00020\u0004XT¢\u0006\u0002\n\u0000R\u000e\u0010\u000f\u001a\u00020\u0004XT¢\u0006\u0002\n\u0000R\u000e\u0010\u0010\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\u0011\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000R\u000e\u0010\u0012\u001a\u00020\u0006XT¢\u0006\u0002\n\u0000¨\u0006\u0016"}, d2 = {"Lcom/wbdl/wand/message/MacroFactory$Companion;", "", "()V", "BLE_MESSAGE_HEADER_SIZE", "", "BUZZ", "", "CHANGE_LED", "CLEAR_LEDS", "COLOR", "DELAY", "DURATION", "GROUP", "LOOPS", "MAX_DURATION", "SECONDS", "SET_LOOP", "SET_LOOPS", "WAIT_BUSY", "fromDoubleByteToIntByte", "d", "", "wand_release"}, k = 1, mv = {1, 7, 1}, xi = 48)
    /* compiled from: MacroFactory.kt */
    public static final class Companion {
        private Companion() {
        }

        public /* synthetic */ Companion(DefaultConstructorMarker defaultConstructorMarker) {
            this();
        }

        /* access modifiers changed from: private */
        public final int fromDoubleByteToIntByte(double d) {
            int i = (int) (d * ((double) 1000));
            if (i > 32767) {
                return 32767;
            }
            return i;
        }
    }

    public MacroFactory(Resources resources2, int i) {
        p.f(resources2, "resources");
        this.resources = resources2;
        this.mtu = i;
    }

    private final List<a> buildBoxMacroList(List<CommandWandbox> list) {
        ArrayList arrayList = new ArrayList();
        for (CommandWandbox buildCommandFromObject : list) {
            a buildCommandFromObject2 = buildCommandFromObject(buildCommandFromObject);
            if (buildCommandFromObject2 != null) {
                arrayList.add(buildCommandFromObject2);
            }
        }
        return arrayList;
    }

    private final y buildBuzz(JSONObject jSONObject) {
        if (!isValidMacro(jSONObject, getBuzzValidation())) {
            return null;
        }
        return new y(Companion.fromDoubleByteToIntByte(jSONObject.getDouble(DURATION)));
    }

    private final a0 buildChangeLed(JSONObject jSONObject) {
        if (!isValidMacro(jSONObject, getChangeLedValidation())) {
            return null;
        }
        return new a0(jSONObject.getInt(GROUP), '#' + jSONObject.getString(COLOR), Companion.fromDoubleByteToIntByte(jSONObject.getDouble(DURATION)));
    }

    private final z buildClearLeds() {
        return new z();
    }

    private final a buildCommandFromMessage(JSONObject jSONObject) {
        if (jSONObject.has("command")) {
            Object obj = jSONObject.get("command");
            if (p.a(obj, WAIT_BUSY)) {
                return buildWaitBusy();
            }
            if (p.a(obj, CLEAR_LEDS)) {
                return buildClearLeds();
            }
            if (p.a(obj, "delay")) {
                return buildDelay(jSONObject);
            }
            if (p.a(obj, BUZZ)) {
                return buildBuzz(jSONObject);
            }
            if (p.a(obj, "changeled")) {
                return buildChangeLed(jSONObject);
            }
            if (p.a(obj, "loop")) {
                return buildSetLoop();
            }
            if (p.a(obj, "setloops")) {
                return buildSetLoops(jSONObject);
            }
            timber.log.a.b("Unhandled command " + obj, new Object[0]);
            return null;
        }
        timber.log.a.b("Invalid macro.", new Object[0]);
        return null;
    }

    private final a buildCommandFromObject(CommandWandbox commandWandbox) {
        String command = commandWandbox.getCommand();
        switch (command.hashCode()) {
            case -1270192235:
                if (command.equals(CLEAR_LEDS)) {
                    return buildClearLeds();
                }
                break;
            case 3035859:
                if (command.equals(BUZZ)) {
                    return buildBuzz(commandWandbox);
                }
                break;
            case 3327652:
                if (command.equals("loop")) {
                    return buildSetLoop();
                }
                break;
            case 95467907:
                if (command.equals("delay")) {
                    return buildDelay(commandWandbox);
                }
                break;
            case 245768430:
                if (command.equals(WAIT_BUSY)) {
                    return buildWaitBusy();
                }
                break;
            case 1427423021:
                if (command.equals("setloops")) {
                    return buildSetLoops(commandWandbox);
                }
                break;
            case 1455272027:
                if (command.equals("changeled")) {
                    return buildChangeLed(commandWandbox);
                }
                break;
        }
        timber.log.a.b("Unhandled command " + commandWandbox, new Object[0]);
        return null;
    }

    private final w buildDelay(JSONObject jSONObject) {
        if (!isValidMacro(jSONObject, getDelayValidation())) {
            return null;
        }
        return new w(Companion.fromDoubleByteToIntByte(jSONObject.getDouble(DURATION)));
    }

    /* JADX WARNING: Code restructure failed: missing block: B:17:0x0052, code lost:
        r0 = move-exception;
     */
    /* JADX WARNING: Code restructure failed: missing block: B:18:0x0053, code lost:
        kotlin.io.c.a(r2, r6);
     */
    /* JADX WARNING: Code restructure failed: missing block: B:19:0x0056, code lost:
        throw r0;
     */
    /* Code decompiled incorrectly, please refer to instructions dump. */
    private final java.util.List<com.wbdl.bluetooth.ble.message.struct.version1.a> buildMacroList(int r6) {
        /*
            r5 = this;
            java.util.ArrayList r0 = new java.util.ArrayList
            r0.<init>()
            android.content.res.Resources r1 = r5.resources
            java.io.InputStream r6 = r1.openRawResource(r6)
            java.lang.String r1 = "resources.openRawResource(resId)"
            kotlin.jvm.internal.p.e(r6, r1)
            java.nio.charset.Charset r1 = kotlin.text.c.b
            java.io.InputStreamReader r2 = new java.io.InputStreamReader
            r2.<init>(r6, r1)
            boolean r6 = r2 instanceof java.io.BufferedReader
            if (r6 == 0) goto L_0x001e
            java.io.BufferedReader r2 = (java.io.BufferedReader) r2
            goto L_0x0026
        L_0x001e:
            java.io.BufferedReader r6 = new java.io.BufferedReader
            r1 = 8192(0x2000, float:1.14794E-41)
            r6.<init>(r2, r1)
            r2 = r6
        L_0x0026:
            r6 = 0
            java.lang.String r1 = kotlin.io.m.d(r2)     // Catch:{ all -> 0x0050 }
            kotlin.io.c.a(r2, r6)
            org.json.JSONArray r6 = new org.json.JSONArray
            r6.<init>(r1)
            r1 = 0
            int r2 = r6.length()
        L_0x0038:
            if (r1 >= r2) goto L_0x004f
            org.json.JSONObject r3 = r6.getJSONObject(r1)
            java.lang.String r4 = "arrayJson.getJSONObject(i)"
            kotlin.jvm.internal.p.e(r3, r4)
            com.wbdl.bluetooth.ble.message.struct.version1.a r3 = r5.buildCommandFromMessage(r3)
            if (r3 == 0) goto L_0x004c
            r0.add(r3)
        L_0x004c:
            int r1 = r1 + 1
            goto L_0x0038
        L_0x004f:
            return r0
        L_0x0050:
            r6 = move-exception
            throw r6     // Catch:{ all -> 0x0052 }
        L_0x0052:
            r0 = move-exception
            kotlin.io.c.a(r2, r6)
            throw r0
        */
        throw new UnsupportedOperationException("Method not decompiled: com.wbdl.wand.message.MacroFactory.buildMacroList(int):java.util.List");
    }

    private final b0 buildSetLoop() {
        return new b0();
    }

    private final c0 buildSetLoops(JSONObject jSONObject) {
        if (!isValidMacro(jSONObject, getSetLoopsValidation())) {
            return null;
        }
        return new c0(jSONObject.getInt(LOOPS));
    }

    private final d0 buildWaitBusy() {
        return new d0();
    }

    private final List<String> getBuzzValidation() {
        return q.e(DURATION);
    }

    private final List<String> getChangeLedValidation() {
        return r.n(GROUP, COLOR, DURATION);
    }

    private final List<String> getDelayValidation() {
        return q.e(DURATION);
    }

    private final List<String> getSetLoopsValidation() {
        return q.e(LOOPS);
    }

    private final boolean isValidMacro(JSONObject jSONObject, List<String> list) {
        if (jSONObject.length() - 1 != list.size()) {
            timber.log.a.b("Parameter count mismatch. Expecting " + list.size() + " received " + jSONObject.length(), new Object[0]);
            return false;
        }
        for (String str : list) {
            if (!jSONObject.has(str)) {
                timber.log.a.b("Invalid macro. Expecting " + str, new Object[0]);
                return false;
            }
        }
        return true;
    }

    public final List<v> buildMacroFromBoxCommandList(List<CommandWandbox> list) {
        p.f(list, "commands");
        return buildMacroMessage((List<? extends a>) buildBoxMacroList(list));
    }

    public final List<v> buildMacroFromCommandList(List<CommandWand> list) {
        p.f(list, "commands");
        return buildMacroMessage((List<? extends a>) buildMacroList(list));
    }

    public final List<v> buildMacroMessage(int i) {
        return buildMacroMessage((List<? extends a>) buildMacroList(i));
    }

    private final List<v> buildMacroMessage(List<? extends a> list) {
        ArrayList arrayList = new ArrayList();
        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        int i = 0;
        for (a aVar : list) {
            if (aVar.a().length + i + 5 + 1 > this.mtu) {
                byte[] byteArray = byteArrayOutputStream.toByteArray();
                p.e(byteArray, "out.toByteArray()");
                arrayList.add(new v(byteArray));
                byteArrayOutputStream.reset();
                i = 0;
            }
            i += aVar.a().length;
            byteArrayOutputStream.write(aVar.a());
        }
        if (byteArrayOutputStream.size() > 0) {
            byte[] byteArray2 = byteArrayOutputStream.toByteArray();
            p.e(byteArray2, "out.toByteArray()");
            arrayList.add(new v(byteArray2));
        }
        return arrayList;
    }

    private final y buildBuzz(CommandWand commandWand) {
        return new y(Companion.fromDoubleByteToIntByte(commandWand.getDuration()));
    }

    private final w buildDelay(CommandWand commandWand) {
        return new w(Companion.fromDoubleByteToIntByte(commandWand.getDuration()));
    }

    private final c0 buildSetLoops(CommandWand commandWand) {
        return new c0(commandWand.getLoops());
    }

    private final y buildBuzz(CommandWandbox commandWandbox) {
        return new y(Companion.fromDoubleByteToIntByte(commandWandbox.getDuration()));
    }

    private final w buildDelay(CommandWandbox commandWandbox) {
        return new w(Companion.fromDoubleByteToIntByte(commandWandbox.getDuration()));
    }

    private final c0 buildSetLoops(CommandWandbox commandWandbox) {
        return new c0(commandWandbox.getLoops());
    }

    private final a0 buildChangeLed(CommandWand commandWand) {
        return new a0(commandWand.getGroup(), '#' + commandWand.getColor(), Companion.fromDoubleByteToIntByte(commandWand.getDuration()));
    }

    private final List<a> buildMacroList(List<CommandWand> list) {
        ArrayList arrayList = new ArrayList();
        for (CommandWand buildCommandFromObject : list) {
            a buildCommandFromObject2 = buildCommandFromObject(buildCommandFromObject);
            if (buildCommandFromObject2 != null) {
                arrayList.add(buildCommandFromObject2);
            }
        }
        return arrayList;
    }

    private final a0 buildChangeLed(CommandWandbox commandWandbox) {
        return new a0(commandWandbox.getGroup(), '#' + commandWandbox.getColor(), Companion.fromDoubleByteToIntByte(commandWandbox.getDuration()));
    }

    private final a buildCommandFromObject(CommandWand commandWand) {
        String command = commandWand.getCommand();
        switch (command.hashCode()) {
            case -1270192235:
                if (command.equals(CLEAR_LEDS)) {
                    return buildClearLeds();
                }
                break;
            case 3035859:
                if (command.equals(BUZZ)) {
                    return buildBuzz(commandWand);
                }
                break;
            case 3327652:
                if (command.equals("loop")) {
                    return buildSetLoop();
                }
                break;
            case 95467907:
                if (command.equals("delay")) {
                    return buildDelay(commandWand);
                }
                break;
            case 245768430:
                if (command.equals(WAIT_BUSY)) {
                    return buildWaitBusy();
                }
                break;
            case 1427423021:
                if (command.equals("setloops")) {
                    return buildSetLoops(commandWand);
                }
                break;
            case 1455272027:
                if (command.equals("changeled")) {
                    return buildChangeLed(commandWand);
                }
                break;
        }
        timber.log.a.b("Unhandled command " + commandWand, new Object[0]);
        return null;
    }
}
