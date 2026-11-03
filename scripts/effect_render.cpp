// Renders a compiled MaiCord background effect (ps_5_0) on WARP, the in-box software rasterizer, so CI without
// a GPU can produce a preview, a clip and a cost measurement. It follows the client's effect pass
// (src/render/d3d11/effect_renderer.cpp, effect_inputs.cpp): the cbuffer McBackground, the built-in textures
// and samplers, premultiplied output, and the three blend modes over a cleared target. The glyph grid is
// rasterized with GDI (Consolas) where the client uses its own outline rasterizer, so glyph edges differ
// slightly. Palette: the default theme's roles, sRGB values used as is. mc_ambient (interface 2) holds a fixed
// moment for the preview: noon on 21 June, and the default theme's dark appearance.
//
// A pass graph (interface 3) is drawn as the client draws it: --cso names a .graph file (effects.graph_text) whose
// lines list the shaders (`shader vs|ps <cso>`), the targets (`target <format> <width> <height> <scale> <persistent>`)
// and the passes (`pass <vs|-1> <ps> <target|-1> <inputs> <blend> <grid w> <grid h> <quads> <clear>`). Every pass
// draws into its target or the effect's output (persistent targets swap planes after each pass that writes them),
// and the output is then composited with the blend mode; the whole graph is the frame the benchmark times.
//
//   effect_render --cso f.cso|f.graph --blend normal|screen|add --uses noise,glyphs,blue_noise,clock,appearance
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

#include <algorithm>
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
    float ambient[4];  // mc_ambient: day, year, month, dark (0 for an input the effect does not use)
    float pass[4];     // mc_pass (interface 3): the pass's target in pixels, then its draw count
};
static_assert(sizeof(Frame) == 336);

// A pass graph (interface 3), as the .graph file lists it.
struct GraphTarget {
    int format, width, height, scale, persistent;
    ID3D11RenderTargetView* views[2];
    ID3D11ShaderResourceView* reads[2];
    int current;
};
struct GraphPass {
    int vertex, pixel, target, inputs, blend, grid[2], quads, clear;
};
struct Graph {
    std::vector<ID3D11VertexShader*> vertex;  // by shader index; null for a pixel shader
    std::vector<ID3D11PixelShader*> pixel;    // null for a vertex shader
    std::vector<GraphTarget> targets;
    std::vector<GraphPass> passes;
};

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

// A render target cleared to transparent black, and its shader view.
ID3D11RenderTargetView* make_target(ID3D11Device* device, ID3D11DeviceContext* context, int width, int height,
                                    DXGI_FORMAT format, ID3D11ShaderResourceView** read) {
    D3D11_TEXTURE2D_DESC description{};
    description.Width = width;
    description.Height = height;
    description.MipLevels = description.ArraySize = 1;
    description.Format = format;
    description.SampleDesc.Count = 1;
    description.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* texture = nullptr;
    check(device->CreateTexture2D(&description, nullptr, &texture), "CreateTexture2D(graph target)");
    ID3D11RenderTargetView* view = nullptr;
    check(device->CreateRenderTargetView(texture, nullptr, &view), "CreateRenderTargetView(graph target)");
    check(device->CreateShaderResourceView(texture, nullptr, read), "CreateShaderResourceView(graph target)");
    texture->Release();
    const float zero[4]{};
    context->ClearRenderTargetView(view, zero);
    return view;
}

// The .graph file: its shaders made, its targets sized for a `width` x `height` output and cleared.
Graph load_graph(ID3D11Device* device, ID3D11DeviceContext* context, const char* path, int width, int height) {
    static const DXGI_FORMAT kFormats[3]{DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_FORMAT_R16G16B16A16_FLOAT,
                                         DXGI_FORMAT_R32G32B32A32_FLOAT};
    std::FILE* file = std::fopen(path, "r");
    if (!file) fail(path);
    Graph graph;
    char line[1200];
    while (std::fgets(line, sizeof(line), file)) {
        char stage[3]{}, shader[1024]{};
        GraphTarget target{};
        GraphPass pass{};
        if (std::sscanf(line, "shader %2s %1023[^\r\n]", stage, shader) == 2) {
            const auto code = read_file(shader);
            ID3D11VertexShader* vertex = nullptr;
            ID3D11PixelShader* pixel = nullptr;
            if (stage[0] == 'v')
                check(device->CreateVertexShader(code.data(), code.size(), nullptr, &vertex), "CreateVertexShader(graph)");
            else
                check(device->CreatePixelShader(code.data(), code.size(), nullptr, &pixel), "CreatePixelShader(graph)");
            graph.vertex.push_back(vertex);
            graph.pixel.push_back(pixel);
        } else if (std::sscanf(line, "target %d %d %d %d %d", &target.format, &target.width, &target.height,
                               &target.scale, &target.persistent) == 5 && target.format >= 0 && target.format < 3) {
            if (target.scale) {
                target.width = std::max(1, (width * target.scale + 50) / 100);
                target.height = std::max(1, (height * target.scale + 50) / 100);
            }
            for (int plane = 0; plane <= target.persistent; ++plane)
                target.views[plane] = make_target(device, context, target.width, target.height, kFormats[target.format],
                                                  &target.reads[plane]);
            graph.targets.push_back(target);
        } else if (std::sscanf(line, "pass %d %d %d %d %d %d %d %d %d", &pass.vertex, &pass.pixel, &pass.target, &pass.inputs,
                               &pass.blend, &pass.grid[0], &pass.grid[1], &pass.quads, &pass.clear) == 9) {
            graph.passes.push_back(pass);
        } else if (line[0] != '\n') {
            fail("cannot read a line of the graph file");
        }
    }
    std::fclose(file);
    for (const auto& pass : graph.passes)
        if (pass.pixel < 0 || pass.pixel >= static_cast<int>(graph.pixel.size()) || !graph.pixel[pass.pixel] ||
            pass.vertex >= static_cast<int>(graph.vertex.size()) || (pass.vertex >= 0 && !graph.vertex[pass.vertex]) ||
            pass.target >= static_cast<int>(graph.targets.size()) || pass.blend < 0 || pass.blend > 3)
            fail("the graph file names a shader or target it does not have");
    return graph;
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
    // As the client's effect_renderer.cpp: no culling, so a graph's grids and quads draw both faces.
    D3D11_RASTERIZER_DESC rasterizer_description{};
    rasterizer_description.FillMode = D3D11_FILL_SOLID;
    rasterizer_description.CullMode = D3D11_CULL_NONE;
    rasterizer_description.DepthClipEnable = TRUE;
    ID3D11RasterizerState* rasterizer = nullptr;
    check(device->CreateRasterizerState(&rasterizer_description, &rasterizer), "CreateRasterizerState");
    context->RSSetState(rasterizer);

    // A .graph file is a pass graph; anything else is the single pixel shader.
    const bool graphed = cso.size() > 6 && cso.compare(cso.size() - 6, 6, ".graph") == 0;
    Graph graph;
    ID3D11PixelShader* pixel_shader = nullptr;
    if (graphed) {
        graph = load_graph(device, context, cso.c_str(), width, height);
    } else {
        const auto bytecode = read_file(cso.c_str());
        check(device->CreatePixelShader(bytecode.data(), bytecode.size(), nullptr, &pixel_shader), "CreatePixelShader");
    }
    static const char kVertex[] =
        "float4 main(uint id : SV_VertexID) : SV_Position {"
        " float2 p = float2((id << 1) & 2, id & 2); return float4(p * float2(2, -2) + float2(-1, 1), 0, 1); }";
    ID3DBlob *vertex_code = nullptr, *errors = nullptr;
    check(D3DCompile(kVertex, sizeof(kVertex) - 1, nullptr, nullptr, nullptr, "main", "vs_5_0", 0, 0, &vertex_code, &errors),
          "D3DCompile(vertex shader)");
    ID3D11VertexShader* vertex_shader = nullptr;
    check(device->CreateVertexShader(vertex_code->GetBufferPointer(), vertex_code->GetBufferSize(), nullptr, &vertex_shader),
          "CreateVertexShader");

    // t0 noise, t1 glyphs, t2 blue noise, t3 to t6 package textures (opaque black when declared).
    ID3D11ShaderResourceView* views[7]{};
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
    const char* const textures[4]{"texture0", "texture1", "texture2", "texture3"};
    for (int i = 0; i < 4; ++i)
        if (has(uses, textures[i])) views[3 + i] = make_view(device, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, &black, 4);
    context->PSSetShaderResources(0, 7, views);

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

    // A graph draws into its own output, which the blend mode then composites like a single pass's picture.
    ID3D11RenderTargetView* output_view = nullptr;
    ID3D11ShaderResourceView* output_read = nullptr;
    ID3D11PixelShader* composite = nullptr;
    ID3D11BlendState* pass_blends[4]{};  // opaque (none), alpha, add, premultiplied
    if (graphed) {
        output_view = make_target(device, context, width, height, DXGI_FORMAT_R8G8B8A8_UNORM, &output_read);
        static const char kComposite[] =
            "Texture2D t : register(t0); float4 main(float4 p : SV_Position) : SV_Target { return t.Load(int3(p.xy, 0)); }";
        ID3DBlob* code = nullptr;
        check(D3DCompile(kComposite, sizeof(kComposite) - 1, nullptr, nullptr, nullptr, "main", "ps_5_0", 0, 0, &code, &errors),
              "D3DCompile(composite)");
        check(device->CreatePixelShader(code->GetBufferPointer(), code->GetBufferSize(), nullptr, &composite),
              "CreatePixelShader(composite)");
        // Source, destination, source alpha, destination alpha, as the client's pass blends.
        const D3D11_BLEND modes[4][4]{{},
                                      {D3D11_BLEND_SRC_ALPHA, D3D11_BLEND_INV_SRC_ALPHA, D3D11_BLEND_ONE, D3D11_BLEND_INV_SRC_ALPHA},
                                      {D3D11_BLEND_ONE, D3D11_BLEND_ONE, D3D11_BLEND_ONE, D3D11_BLEND_ONE},
                                      {D3D11_BLEND_ONE, D3D11_BLEND_INV_SRC_ALPHA, D3D11_BLEND_ONE, D3D11_BLEND_INV_SRC_ALPHA}};
        for (int i = 1; i < 4; ++i) {
            D3D11_BLEND_DESC description{};
            auto& pass_blend = description.RenderTarget[0];
            pass_blend.BlendEnable = TRUE;
            pass_blend.SrcBlend = modes[i][0];
            pass_blend.DestBlend = modes[i][1];
            pass_blend.BlendOp = D3D11_BLEND_OP_ADD;
            pass_blend.SrcBlendAlpha = modes[i][2];
            pass_blend.DestBlendAlpha = modes[i][3];
            pass_blend.BlendOpAlpha = D3D11_BLEND_OP_ADD;
            pass_blend.RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
            check(device->CreateBlendState(&description, &pass_blends[i]), "CreateBlendState(pass)");
        }
        context->VSSetConstantBuffers(0, 1, &constants);
        context->VSSetSamplers(0, 3, samplers);
    }

    Frame frame{};
    std::memcpy(frame.palette, kPalette, sizeof(kPalette));
    frame.dark = 1;
    frame.intensity = 1;
    frame.dip = dip;
    frame.resolution[0] = static_cast<float>(width);
    frame.resolution[1] = static_cast<float>(height);
    frame.pointer[0] = frame.pointer[1] = -1;
    std::memcpy(frame.knobs, knobs, sizeof(knobs));
    if (has(uses, "clock")) {
        frame.ambient[0] = 0.5f;                     // 12:00
        frame.ambient[1] = (171.0f + 0.5f) / 365.0f;  // 21 June at noon
        frame.ambient[2] = 6.0f;                     // June
    }
    if (has(uses, "appearance")) frame.ambient[3] = 1.0f;
    const float clear[4]{kPalette[0][0], kPalette[0][1], kPalette[0][2], 1};

    // Every pass in order, as the client's draw_frame does, then the output bound for the composite below.
    auto draw_graph = [&]() {
        ID3D11ShaderResourceView* none[11]{};
        for (const auto& pass : graph.passes) {
            ID3D11RenderTargetView* view = output_view;
            int pass_width = width, pass_height = height;
            GraphTarget* written = nullptr;
            if (pass.target >= 0) {
                // A persistent target draws its other plane: the pass reads the last state and writes the next.
                written = &graph.targets[pass.target];
                view = written->views[written->current ^ written->persistent];
                pass_width = written->width;
                pass_height = written->height;
            }
            ID3D11ShaderResourceView* reads[11]{};
            std::copy(views, views + 7, reads);
            for (size_t t = 0; t < graph.targets.size(); ++t)
                if (pass.inputs >> t & 1) reads[7 + t] = graph.targets[t].reads[graph.targets[t].current];
            context->PSSetShaderResources(0, 11, none);
            context->VSSetShaderResources(0, 11, none);
            context->OMSetRenderTargets(1, &view, nullptr);
            const D3D11_VIEWPORT pass_viewport{0, 0, static_cast<float>(pass_width), static_cast<float>(pass_height), 0, 1};
            context->RSSetViewports(1, &pass_viewport);
            if (pass.clear) {
                const float zero[4]{};
                context->ClearRenderTargetView(view, zero);
            }
            context->PSSetShaderResources(0, 11, reads);
            context->VSSetShaderResources(0, 11, reads);
            context->VSSetShader(pass.vertex >= 0 ? graph.vertex[pass.vertex] : vertex_shader, nullptr, 0);
            context->PSSetShader(graph.pixel[pass.pixel], nullptr, 0);
            context->OMSetBlendState(pass_blends[pass.blend], nullptr, 0xFFFFFFFFu);
            const bool grid = pass.grid[0] > 0;
            frame.pass[0] = static_cast<float>(pass_width);
            frame.pass[1] = static_cast<float>(pass_height);
            frame.pass[2] = static_cast<float>(grid ? pass.grid[0] : pass.quads);
            frame.pass[3] = static_cast<float>(grid ? pass.grid[1] : pass.quads ? 1 : 0);
            context->UpdateSubresource(constants, 0, nullptr, &frame, 0, 0);
            if (pass.vertex < 0) {
                context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
                context->Draw(3, 0);
            } else {
                // grid(W, H): H - 1 instanced strips of 2W vertices; quads(N): N instanced strips of four.
                context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP);
                context->DrawInstanced(grid ? 2 * pass.grid[0] : 4, grid ? pass.grid[1] - 1 : pass.quads, 0, 0);
            }
            if (written) written->current ^= written->persistent;
        }
        context->PSSetShaderResources(0, 11, none);
        context->VSSetShaderResources(0, 11, none);
        context->OMSetRenderTargets(1, &target_view, nullptr);
        context->RSSetViewports(1, &viewport);
        context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context->VSSetShader(vertex_shader, nullptr, 0);
        context->PSSetShader(composite, nullptr, 0);
        context->PSSetShaderResources(0, 1, &output_read);
        context->OMSetBlendState(blend_state, factor, 0xFFFFFFFFu);
    };
    auto draw = [&](float time, float index) {
        frame.time = time;
        frame.delta = 1.0f / fps;
        frame.frame = index;
        if (graphed) draw_graph();
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
