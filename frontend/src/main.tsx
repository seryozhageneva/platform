import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./style.css";

function takeStudentLink() {
  const link = new URLSearchParams(window.location.hash.slice(1)).get("student");
  if (link !== null) {
    const { pathname, search } = window.location;
    window.history.replaceState(null, "", pathname + search);
  }
  return link;
}

const root = createRoot(document.getElementById("root")!);
let entry = 0;
root.render(<App key={entry} link={takeStudentLink()} />);

window.addEventListener("hashchange", () => {
  const link = takeStudentLink();
  if (link !== null) {
    root.render(<App key={++entry} link={link} />);
  }
});
