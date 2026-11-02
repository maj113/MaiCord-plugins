// Renders a compiled MaiCord background effect (ps_5_0) on WARP, the in-box software rasterizer, so CI without
// a GPU can produce a preview, a clip and a cost measurement. It follows the client's effect pass
// (src/render/d3d11/effect_renderer.cpp, effect_inputs.cpp): the cbuffer McBackground, the built-in textures
// and samplers, premultiplied output, and the three blend modes over a cleared target. The glyph grid is
// rasterized with GDI (Consolas) where the client uses its own outline rasterizer, so glyph edges differ
// slightly. Palette: the default theme's roles, sRGB values used as is.
//
//   effect_render --cso f.cso --blend normal|screen|add --uses noise,glyphs,blue_noise
//                 --blue blue_noise_64.bin --knobs v0,v1,...,v31 --size 960x540 --dip 1
//                 --fps 15 --t0 2 --frames 1 --out frames.rgba         raw RGBA8, frames back to back
//   effect_render ... --bench 300                                      prints the milliseconds per frame
//
// Build: clang-cl /O2 /EHsc effect_render.cpp user32.lib gdi32.lib /Fe:effect_render.exe
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

struct Frame {
    float time, delta, frame, dip;
    float resolution[2], pointer[2];
    float palette[8][4];
    float dark, intensity, reserved[2];
    float knobs[8][4];
};
static_assert(sizeof(Frame) == 304);

// The default theme's roles (assets/themes/example.maicord-theme.json): background, surface, text, muted,
// accent, positive, warning, critical.
const float kPalette[8][4] = {{0.1333f, 0.1333f, 0.1451f, 1}, {0.1647f, 0.1647f, 0.1804f, 1},
                              {0.9490f, 0.9569f, 0.9686f, 1}, {0.7098f, 0.7294f, 0.7569f, 1},
                              {0.3451f, 0.3961f, 0.9490f, 1}, {0.14f, 0.65f, 0.38f, 1},
                              {0.94f, 0.69f, 0.2f, 1},        {0.9490f, 0.3216f, 0.3216f, 1}};

[[noreturn]] void fail(const char* what, HRESULT result = 0) {
    std::fprintf(stderr, "effect_render: %s (0x%08lx)\n", what, static_cast<unsigned long>(result));
    std::exit(1);
}
void check(HRESULT result, const char* what) {
    if (FAILED(result)) fail(what, result);
}

std::vector<uint8_t> read_file(const char* path) {
    std::FILE* file = std::fopen(path, "rb");
    if (!file) fail(path);
    std::vector<uint8_t> data;
    uint8_t buffer[65536];
    for (size_t n; (n = std::fread(buffer, 1, sizeof(buffer), file)) > 0;) data.insert(data.end(), buffer, buffer + n);
    std::fclose(file);
    return data;
}

uint32_t pcg(uint32_t index) {
    const uint32_t state = index * 747796405u + 2891336453u;
    const uint32_t word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

ID3D11ShaderResourceView* make_view(ID3D11Device* device, UINT width, UINT height, DXGI_FORMAT format,
                                    const void* pixels, UINT pitch) {
    D3D11_TEXTURE2D_DESC description{};
    description.Width = width;
    description.Height = height;
    description.MipLevels = description.ArraySize = 1;
    description.Format = format;
    description.SampleDesc.Count = 1;
    description.Usage = D3D11_USAGE_IMMUTABLE;
    description.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    const D3D11_SUBRESOURCE_DATA data{pixels, pitch, 0};
    ID3D11Texture2D* texture = nullptr;
    check(device->CreateTexture2D(&description, &data, &texture), "CreateTexture2D");
    ID3D11ShaderResourceView* view = nullptr;
    check(device->CreateShaderResourceView(texture, nullptr, &view), "CreateShaderResourceView");
    texture->Release();
    return view;
}

// 16x16 cells of 32 pixels, cell = Latin-1 code point, R8 coverage; the baseline sits 24 pixels down.
ID3D11ShaderResourceView* make_glyph_grid(ID3D11Device* device) {
    constexpr int kExtent = 512, kCell = 32;
    BITMAPINFO info{};
    info.bmiHeader = {sizeof(BITMAPINFOHEADER), kExtent, -kExtent, 1, 32, BI_RGB};
    void* bits = nullptr;
    HDC context = CreateCompatibleDC(nullptr);
    HBITMAP bitmap = CreateDIBSection(context, &info, DIB_RGB_COLORS, &bits, nullptr, 0);
    SelectObject(context, bitmap);
    HFONT font = CreateFontW(-24, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, OUT_TT_ONLY_PRECIS, CLIP_DEFAULT_PRECIS,
                             ANTIALIASED_QUALITY, FIXED_PITCH | FF_MODERN, L"Consolas");
    SelectObject(context, font);
    SetBkColor(context, 0);
    SetTextColor(context, 0xFFFFFF);
    SetTextAlign(context, TA_LEFT | TA_BASELINE);
    std::memset(bits, 0, kExtent * kExtent * 4);
    for (int code = 33; code < 256; ++code) {
        if (code >= 127 && code < 161) continue;
        const wchar_t letter = static_cast<wchar_t>(code);
        SIZE size{};
        GetTextExtentPoint32W(context, &letter, 1, &size);
        const int x = (code & 15) * kCell + (kCell - size.cx) / 2, y = (code >> 4) * kCell + 24;
        ExtTextOutW(context, x, y, ETO_CLIPPED, nullptr, &letter, 1, nullptr);
    }
    GdiFlush();
    std::vector<uint8_t> coverage(kExtent * kExtent);
    const auto* source = static_cast<const uint32_t*>(bits);
    for (int i = 0; i < kExtent * kExtent; ++i) coverage[i] = static_cast<uint8_t>((source[i] >> 8) & 0xFF);
    auto* view = make_view(device, kExtent, kExtent, DXGI_FORMAT_R8_UNORM, coverage.data(), kExtent);
    DeleteObject(font);
    DeleteObject(bitmap);
    DeleteDC(context);
    return view;
}

bool has(const std::string& list, const char* word) {
    return ("," + list + ",").find(std::string(",") + word + ",") != std::string::npos;
}

}  // namespace

int main(int argc, char** argv) {
    std::string cso, blend = "normal", uses, blue, out;
    float knobs[32]{};
    int width = 960, height = 540, frames = 1, bench = 0;
    float dip = 1, fps = 15, t0 = 2;
    for (int i = 1; i < argc; i += 2) {
        const std::string name = argv[i];
        if (i + 1 >= argc) fail("every option takes a value");
        const char* value = argv[i + 1];
        if (name == "--cso") cso = value;
        else if (name == "--blend") blend = value;
        else if (name == "--uses") uses = value;
        else if (name == "--blue") blue = value;
        else if (name == "--out") out = value;
        else if (name == "--dip") dip = static_cast<float>(std::atof(value));
        else if (name == "--fps") fps = static_cast<float>(std::atof(value));
        else if (name == "--t0") t0 = static_cast<float>(std::atof(value));
        else if (name == "--frames") frames = std::atoi(value);
        else if (name == "--bench") bench = std::atoi(value);
        else if (name == "--size") std::sscanf(value, "%dx%d", &width, &height);
        else if (name == "--knobs") {
            const char* at = value;
            for (int k = 0; k < 32 && *at; ++k) {
                knobs[k] = static_cast<float>(std::strtod(at, const_cast<char**>(&at)));
                if (*at == ',') ++at;
            }
        } else fail("unknown argument");
    }
    if (cso.empty() || width < 1 || height < 1 || frames < 1) fail("usage: --cso f.cso [--size WxH] [--frames N] --out f.rgba");

    const D3D_FEATURE_LEVEL levels[]{D3D_FEATURE_LEVEL_11_0};
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* context = nullptr;
    check(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, levels, 1, D3D11_SDK_VERSION, &device, nullptr,
                            &context), "D3D11CreateDevice(WARP)");

    const auto bytecode = read_file(cso.c_str());
    ID3D11PixelShader* pixel_shader = nullptr;
    check(device->CreatePixelShader(bytecode.data(), bytecode.size(), nullptr, &pixel_shader), "CreatePixelShader");
    static const char kVertex[] =
        "float4 main(uint id : SV_VertexID) : SV_Position {"
        " float2 p = float2((id << 1) & 2, id & 2); return float4(p * float2(2, -2) + float2(-1, 1), 0, 1); }";
    ID3DBlob *vertex_code = nullptr, *errors = nullptr;
    check(D3DCompile(kVertex, sizeof(kVertex) - 1, nullptr, nullptr, nullptr, "main", "vs_5_0", 0, 0, &vertex_code, &errors),
          "D3DCompile(vertex shader)");
    ID3D11VertexShader* vertex_shader = nullptr;
    check(device->CreateVertexShader(vertex_code->GetBufferPointer(), vertex_code->GetBufferSize(), nullptr, &vertex_shader),
          "CreateVertexShader");

    // t0 noise, t1 glyphs, t2 blue noise, t3 and t4 package textures (opaque black when declared).
    ID3D11ShaderResourceView* views[5]{};
    if (has(uses, "noise")) {
        std::vector<uint32_t> noise(256 * 256);
        for (uint32_t i = 0; i < noise.size(); ++i) noise[i] = pcg(i);
        views[0] = make_view(device, 256, 256, DXGI_FORMAT_R8G8B8A8_UNORM, noise.data(), 256 * 4);
    }
    if (has(uses, "glyphs")) views[1] = make_glyph_grid(device);
    if (has(uses, "blue_noise")) {
        const auto table = blue.empty() ? std::vector<uint8_t>() : read_file(blue.c_str());
        if (table.size() != 4096) fail("--blue must name the 4096-byte blue noise table");
        views[2] = make_view(device, 64, 64, DXGI_FORMAT_R8_UNORM, table.data(), 64);
    }
    const uint32_t black = 0xFF000000u;
    if (has(uses, "texture0")) views[3] = make_view(device, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, &black, 4);
    if (has(uses, "texture1")) views[4] = make_view(device, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, &black, 4);
    context->PSSetShaderResources(0, 5, views);

    ID3D11SamplerState* samplers[3]{};
    const D3D11_FILTER filters[3]{D3D11_FILTER_MIN_MAG_MIP_POINT, D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT,
                                  D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT};
    const D3D11_TEXTURE_ADDRESS_MODE modes[3]{D3D11_TEXTURE_ADDRESS_WRAP, D3D11_TEXTURE_ADDRESS_WRAP,
                                              D3D11_TEXTURE_ADDRESS_CLAMP};
    for (int i = 0; i < 3; ++i) {
        D3D11_SAMPLER_DESC description{};
        description.Filter = filters[i];
        description.AddressU = description.AddressV = description.AddressW = modes[i];
        description.MaxLOD = D3D11_FLOAT32_MAX;
        check(device->CreateSamplerState(&description, &samplers[i]), "CreateSamplerState");
    }
    context->PSSetSamplers(0, 3, samplers);

    // The target holds premultiplied colour; every mode adds the source and weighs what is behind it.
    const int mode = blend == "screen" ? 1 : blend == "add" ? 2 : 0;
    D3D11_BLEND_DESC blend_description{};
    auto& target_blend = blend_description.RenderTarget[0];
    target_blend.BlendEnable = TRUE;
    target_blend.SrcBlend = D3D11_BLEND_BLEND_FACTOR;
    target_blend.DestBlend = mode == 0 ? D3D11_BLEND_INV_SRC_ALPHA : mode == 1 ? D3D11_BLEND_INV_SRC_COLOR : D3D11_BLEND_ONE;
    target_blend.BlendOp = D3D11_BLEND_OP_ADD;
    target_blend.SrcBlendAlpha = mode == 0 ? D3D11_BLEND_BLEND_FACTOR : D3D11_BLEND_ZERO;
    target_blend.DestBlendAlpha = mode == 0 ? D3D11_BLEND_INV_SRC_ALPHA : D3D11_BLEND_ONE;
    target_blend.BlendOpAlpha = D3D11_BLEND_OP_ADD;
    target_blend.RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    ID3D11BlendState* blend_state = nullptr;
    check(device->CreateBlendState(&blend_description, &blend_state), "CreateBlendState");
    const float factor[4]{1, 1, 1, 1};
    context->OMSetBlendState(blend_state, factor, 0xFFFFFFFFu);

    D3D11_BUFFER_DESC buffer_description{sizeof(Frame), D3D11_USAGE_DEFAULT, D3D11_BIND_CONSTANT_BUFFER, 0, 0, 0};
    ID3D11Buffer* constants = nullptr;
    check(device->CreateBuffer(&buffer_description, nullptr, &constants), "CreateBuffer");

    D3D11_TEXTURE2D_DESC target_description{};
    target_description.Width = width;
    target_description.Height = height;
    target_description.MipLevels = target_description.ArraySize = 1;
    target_description.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    target_description.SampleDesc.Count = 1;
    target_description.BindFlags = D3D11_BIND_RENDER_TARGET;
    ID3D11Texture2D* target = nullptr;
    check(device->CreateTexture2D(&target_description, nullptr, &target), "CreateTexture2D(target)");
    ID3D11RenderTargetView* target_view = nullptr;
    check(device->CreateRenderTargetView(target, nullptr, &target_view), "CreateRenderTargetView");
    target_description.Usage = D3D11_USAGE_STAGING;
    target_description.BindFlags = 0;
    target_description.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* staging = nullptr;
    check(device->CreateTexture2D(&target_description, nullptr, &staging), "CreateTexture2D(staging)");

    const D3D11_VIEWPORT viewport{0, 0, static_cast<float>(width), static_cast<float>(height), 0, 1};
    context->RSSetViewports(1, &viewport);
    context->OMSetRenderTargets(1, &target_view, nullptr);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->VSSetShader(vertex_shader, nullptr, 0);
    context->PSSetShader(pixel_shader, nullptr, 0);
    context->PSSetConstantBuffers(0, 1, &constants);

    Frame frame{};
    std::memcpy(frame.palette, kPalette, sizeof(kPalette));
    frame.dark = 1;
    frame.intensity = 1;
    frame.dip = dip;
    frame.resolution[0] = static_cast<float>(width);
    frame.resolution[1] = static_cast<float>(height);
    frame.pointer[0] = frame.pointer[1] = -1;
    std::memcpy(frame.knobs, knobs, sizeof(knobs));
    const float clear[4]{kPalette[0][0], kPalette[0][1], kPalette[0][2], 1};

    auto draw = [&](float time, float index) {
        frame.time = time;
        frame.delta = 1.0f / fps;
        frame.frame = index;
        context->UpdateSubresource(constants, 0, nullptr, &frame, 0, 0);
        context->ClearRenderTargetView(target_view, clear);
        context->Draw(3, 0);
    };
    auto read_back = [&](std::vector<uint8_t>* pixels) {
        context->CopyResource(staging, target);
        D3D11_MAPPED_SUBRESOURCE mapped{};
        check(context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped), "Map");
        if (pixels)
            for (int y = 0; y < height; ++y)
                pixels->insert(pixels->end(), static_cast<uint8_t*>(mapped.pData) + static_cast<size_t>(y) * mapped.RowPitch,
                               static_cast<uint8_t*>(mapped.pData) + static_cast<size_t>(y) * mapped.RowPitch + width * 4);
        context->Unmap(staging, 0);
    };

    if (bench) {
        draw(t0, 0);  // the first frame pays for lazy state
        read_back(nullptr);
        LARGE_INTEGER frequency, begin, end;
        QueryPerformanceFrequency(&frequency);
        QueryPerformanceCounter(&begin);
        for (int i = 1; i <= bench; ++i) draw(t0 + static_cast<float>(i) / fps, static_cast<float>(i));
        read_back(nullptr);
        QueryPerformanceCounter(&end);
        std::printf("%.4f\n", 1000.0 * static_cast<double>(end.QuadPart - begin.QuadPart) /
                                   static_cast<double>(frequency.QuadPart) / bench);
        return 0;
    }

    if (out.empty()) fail("--out is required");
    std::vector<uint8_t> pixels;
    pixels.reserve(static_cast<size_t>(width) * height * 4 * frames);
    for (int i = 0; i < frames; ++i) {
        draw(t0 + static_cast<float>(i) / fps, t0 * fps + static_cast<float>(i));
        read_back(&pixels);
    }
    std::FILE* file = std::fopen(out.c_str(), "wb");
    if (!file || std::fwrite(pixels.data(), 1, pixels.size(), file) != pixels.size()) fail("cannot write --out");
    std::fclose(file);
    return 0;
}
