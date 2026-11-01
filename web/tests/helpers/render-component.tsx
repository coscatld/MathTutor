import React, {type ReactNode} from "react";
import {renderToStaticMarkup} from "react-dom/server";

/** Capture event handlers while React supplies the real server-render dispatcher. */
export function renderComponentTree<Props>(Component: (props: Props) => ReactNode, props: Props): ReactNode {
  let tree: ReactNode = null;
  function Capture() {
    tree = Component(props);
    return <>{tree}</>;
  }
  renderToStaticMarkup(<Capture />);
  return tree;
}
