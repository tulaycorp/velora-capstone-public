import {
  BarChart3,
  Boxes,
  ClipboardList,
  Home,
  Layers3,
  PackageOpen,
  Settings,
  Wand2
} from "lucide-react";

export const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: Home },
  { href: "/product-studio", label: "Product Studio", icon: Wand2 },
  { href: "/blueprints", label: "Blueprints", icon: Layers3 },
  { href: "/products", label: "Products", icon: Boxes },
  { href: "/orders", label: "Orders", icon: ClipboardList },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings }
];

export const storeContexts = [
  { id: "all", label: "All Stores" },
  { id: "printify-etsy", label: "Printify / Etsy Shop" },
  { id: "printify-shopify", label: "Printify / Shopify Store" },
  { id: "gelato-etsy", label: "Gelato / Etsy Shop" },
  { id: "gelato-shopify", label: "Gelato / Shopify Store" }
];

export const products = [
  {
    name: "Minimalist Abstract Wall Art",
    type: "Canvas print",
    provider: "Printify",
    store: "Printify / Etsy Shop",
    status: "Published",
    cost: "$34.39",
    margin: "$18.40",
    price: "$52.79",
    readiness: "Ready",
    updated: "12 min ago",
    image:
      "https://images.unsplash.com/photo-1541961017774-22349e4a1262?auto=format&fit=crop&w=160&q=80"
  },
  {
    name: "Botanical Framed Poster",
    type: "Framed poster",
    provider: "Gelato",
    store: "Gelato / Shopify Store",
    status: "Ready",
    cost: "$26.90",
    margin: "$21.10",
    price: "$48.00",
    readiness: "Review",
    updated: "28 min ago",
    image:
      "https://images.unsplash.com/photo-1501004318641-b39e6451bec6?auto=format&fit=crop&w=160&q=80"
  },
  {
    name: "Vintage Landscape Canvas",
    type: "Canvas print",
    provider: "Printify",
    store: "Printify / Shopify Store",
    status: "Created in Provider",
    cost: "$39.75",
    margin: "$24.25",
    price: "$64.00",
    readiness: "Syncing",
    updated: "1 hr ago",
    image:
      "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=160&q=80"
  },
  {
    name: "Typography Tote Bag",
    type: "Tote bag",
    provider: "Gelato",
    store: "Gelato / Etsy Shop",
    status: "Draft",
    cost: "$16.20",
    margin: "$9.80",
    price: "$26.00",
    readiness: "Draft",
    updated: "Yesterday",
    image:
      "https://images.unsplash.com/photo-1597484662317-9bd7bdda2907?auto=format&fit=crop&w=160&q=80"
  }
];

export const blueprints = [
  {
    id: "minimalist-canvas-printify-etsy",
    name: "Minimalist Abstract Wall Art",
    category: "Wall art",
    provider: "Printify",
    store: "Printify / Etsy Shop",
    referenceType: "Printify product URL",
    referenceValue: "https://printify.com/app/products/784512",
    productType: "Canvas 16x20",
    configuration: "Canvas 16x20, 3 variants, front print area",
    baseCost: "$34.39",
    retailPrice: "$52.79",
    margin: "$18.40",
    drafts: 2,
    status: "Active"
  },
  {
    id: "botanical-poster-gelato-shopify",
    name: "Botanical Framed Poster",
    category: "Posters",
    provider: "Gelato",
    store: "Gelato / Shopify Store",
    referenceType: "Gelato template ID",
    referenceValue: "gelato_tpl_12x16_frame_oak",
    productType: "Framed poster 12x16",
    configuration: "Framed poster 12x16, oak frame, matte paper",
    baseCost: "$26.90",
    retailPrice: "$48.00",
    margin: "$21.10",
    drafts: 1,
    status: "Active"
  },
  {
    id: "pet-mug-printify-shopify",
    name: "Custom Pet Portrait Mug",
    category: "Mugs",
    provider: "Printify",
    store: "Printify / Shopify Store",
    referenceType: "Printify product URL",
    referenceValue: "https://printify.com/app/products/552901",
    productType: "Ceramic mug 11oz",
    configuration: "Ceramic mug 11oz, white, wrap print area",
    baseCost: "$7.20",
    retailPrice: "$19.00",
    margin: "$11.80",
    drafts: 0,
    status: "Draft"
  }
];

export const orders = [
  {
    id: "VL-1007",
    product: "Minimalist Abstract Wall Art",
    provider: "Printify",
    store: "Printify / Etsy Shop",
    status: "In production",
    total: "$64.00"
  },
  {
    id: "VL-1008",
    product: "Botanical Framed Poster",
    provider: "Gelato",
    store: "Gelato / Shopify Store",
    status: "Submitted",
    total: "$48.00"
  }
];

export const providers = [
  {
    name: "Printify",
    status: "Connected",
    stores: ["Printify / Etsy Shop", "Printify / Shopify Store"],
    sync: "12 minutes ago"
  },
  {
    name: "Gelato",
    status: "Connected",
    stores: ["Gelato / Etsy Shop", "Gelato / Shopify Store"],
    sync: "25 minutes ago"
  }
];

export const emptyIcon = PackageOpen;
