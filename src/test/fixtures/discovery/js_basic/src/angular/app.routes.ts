import { Routes } from "@angular/router";
import { AppComponent } from "./app.component";

export const routes: Routes = [
  { path: "dashboard", component: AppComponent },
  { path: "lazy", loadChildren: () => import("./lazy.module") },
];
